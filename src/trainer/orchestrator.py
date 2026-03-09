"""Orchestrator v2 — 5-phase walkthrough-first training loop.

Key changes from v1:
- Claude CLI ($0 via Max subscription) instead of Agent SDK (API credits)
- Per-finding micro-queries instead of monolithic agent calls
- Orchestrator controls ALL pipeline runs (agent cannot run pipeline)
- Maximum 2 pipeline runs per case, ever
- Walkthrough analysis is exhaustive before any pipeline run

Phases:
  1. Walkthrough dissection (0 pipeline runs)
  2. First pipeline run (#1 of max 2)
  3. Post-run gap analysis (0 pipeline runs)
  4. Final pipeline run (#2 of max 2)
  5. Approval & commit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from trainer import agent_prompts
from trainer.claude_runner import ClaudeResult, check_pipeline_leak, invoke
from trainer.config import Config, load_config
from trainer.cost_tracker import BudgetExceeded, CostEntry, CostTracker
from trainer.notifier import Notifier, TelegramApprovalBot
from trainer.state import CycleScore, InvalidTransition, State, StateMachine

logger = logging.getLogger(__name__)

MAX_PIPELINE_RUNS = 2


class Orchestrator:
    """Main training loop orchestrator — v2 walkthrough-first strategy."""

    def __init__(self, config: Config):
        self.config = config
        self.state = StateMachine(config.state_dir)
        self.cost_tracker = CostTracker(
            state_dir=config.state_dir,
            max_per_cycle_usd=config.budget.max_per_cycle_usd,
            max_total_usd=config.budget.max_total_usd,
            warn_threshold_pct=config.budget.warn_threshold_pct,
        )
        self.notifier = Notifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self.templates_dir = config.project_root / "templates"
        self._system_prompt = agent_prompts.system_prompt(self.templates_dir)
        self._pipeline_runs = 0

    # --- Agent query wrapper ---

    async def _query(
        self,
        prompt: str,
        label: str = "",
        timeout: int = 300,
        max_turns: int = 50,
    ) -> ClaudeResult:
        """Run a single agent query via CLI. Records cost, checks for pipeline leaks."""
        logger.info("Query [%s]: %s", label, prompt[:120])

        result = await invoke(
            prompt=prompt,
            timeout=timeout,
            max_turns=max_turns,
            allowed_tools="Read,Write,Edit,Bash,Glob,Grep",
            system_prompt=self._system_prompt,
            cwd=str(self.config.target.local_path),
            cli_path=self.config.cli_path or "claude",
        )

        # Record cost (usually $0 with Max subscription)
        self._record_cost(
            self.state.current.case_name,
            self.state.current.cycle,
            label,
            result.cost_usd,
        )

        # Post-query validation: check for pipeline execution attempts
        if result.result:
            violations = check_pipeline_leak(result.result)
            if violations:
                logger.warning(
                    "PIPELINE LEAK DETECTED in [%s]: %s", label, violations
                )

        if not result.success:
            logger.error("Query [%s] failed: %s (%s)", label, result.error, result.error_type)

        return result

    def _extract_json(self, text: str) -> dict | None:
        """Try to extract a JSON object from agent response text."""
        # Look for ```json ... ``` blocks first
        import re
        json_match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try raw JSON parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Scan for JSON object boundaries
        for i, ch in enumerate(text):
            if ch == "{":
                for j in range(len(text), i, -1):
                    if text[j - 1] == "}":
                        try:
                            return json.loads(text[i:j])
                        except json.JSONDecodeError:
                            continue
        return None

    # --- Pipeline runner (orchestrator-controlled) ---

    def _run_pipeline(self, case_name: str, extraction_only: bool = False) -> tuple[str, float | None]:
        """Run the ARGUS pipeline directly via subprocess. Returns (output, score).

        This is the ONLY place pipeline commands are executed.
        """
        cmd = [
            str(self.config.target.venv_path / "bin" / "python"),
            "improvement/runner.py", "run", case_name,
        ]
        if extraction_only:
            cmd.append("--extraction-only")

        timeout = (
            self.config.runner.extraction_timeout if extraction_only
            else self.config.runner.run_timeout
        )

        label = "extraction-only" if extraction_only else "full pipeline"
        logger.info("Running %s for %s (timeout=%ds)", label, case_name, timeout)

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.config.target.local_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout + "\n" + result.stderr
            logger.info("Pipeline %s exit code: %d", label, result.returncode)

            # Try to parse score from output
            score = self._parse_score(output)
            return output, score

        except subprocess.TimeoutExpired:
            logger.error("Pipeline %s timed out after %ds", label, timeout)
            return f"Pipeline timed out after {timeout}s", None
        except Exception as e:
            logger.exception("Pipeline %s failed", label)
            return str(e), None

    def _run_comparison(self, case_name: str) -> tuple[str, float | None]:
        """Run the comparator to get score and gap analysis."""
        cmd = [
            str(self.config.target.venv_path / "bin" / "python"),
            "improvement/comparator.py", case_name,
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.config.target.local_path),
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout + "\n" + result.stderr
            score = self._parse_score(output)
            return output, score
        except Exception as e:
            logger.exception("Comparison failed")
            return str(e), None

    # --- Main training loop ---

    async def run_cycle(
        self,
        case_name: str,
        dry_run: bool = False,
    ) -> None:
        """Run the full 5-phase improvement loop for a case."""
        cycle = self.state.current.cycle + 1
        self.state.init_cycle(case_name, cycle)
        self.cost_tracker.reset_cycle()
        self._pipeline_runs = 0

        answer_key_path = f"improvement/cases/{case_name}/answer_key.json"

        await self.notifier.send_cycle_start(case_name, cycle)

        if dry_run:
            logger.info("[DRY RUN] Would start cycle %d for case %s", cycle, case_name)
            await self.notifier.send(
                f"*DRY RUN* — Cycle {cycle} for `{case_name}` initialized. Stopping."
            )
            return

        try:
            # Create git branch
            branch = self.config.git.branch_pattern.format(cycle=cycle, case=case_name)
            self.state.current.current_branch = branch
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=str(self.config.target.local_path),
                capture_output=True,
            )

            # ==========================================
            # PHASE 1: Walkthrough Dissection
            # ==========================================
            await self.notifier.send(
                f"*Phase 1* — Walkthrough dissection for `{case_name}`\n"
                f"Pipeline runs: 0/{MAX_PIPELINE_RUNS}"
            )

            # Step 1.1: Fetch walkthrough
            self.state.transition(State.FETCHING_WALKTHROUGH)
            case_config = next(
                (c for c in self.config.cases if c.name == case_name), None
            )
            walkthrough_url = case_config.walkthrough_url if case_config else ""

            fetch_prompt = agent_prompts.build_fetch_walkthrough_prompt(
                case_name, walkthrough_url
            )
            fetch_result = await self._query(fetch_prompt, "phase1_fetch", timeout=180)
            if not fetch_result.success:
                raise RuntimeError(f"Failed to fetch walkthrough: {fetch_result.error}")

            walkthrough_content = fetch_result.result

            # Step 1.2: Build answer key
            self.state.transition(State.BUILDING_ANSWER_KEY)
            answer_key_prompt = agent_prompts.build_answer_key_prompt(
                self.templates_dir, case_name, walkthrough_content
            )
            ak_result = await self._query(answer_key_prompt, "phase1_answer_key", timeout=300)
            if not ak_result.success:
                raise RuntimeError(f"Failed to build answer key: {ak_result.error}")

            # Load the answer key the agent wrote
            findings = self._load_answer_key(answer_key_path)
            if not findings:
                raise RuntimeError(
                    f"Answer key not found or empty at {answer_key_path}. "
                    f"Agent response: {ak_result.result[:200]}"
                )

            await self.notifier.send(
                f"*Phase 1.2* — Answer key built: {len(findings)} findings"
            )

            # Step 1.3: Per-finding deep audit
            self.state.transition(State.ANALYZING_GAPS)
            audit_results = await self._audit_findings(case_name, findings)

            # Step 1.4: Implement + unit test each fix
            self.state.transition(State.IMPLEMENTING_FIXES)
            fixes_needed = [
                (f, a) for f, a in zip(findings, audit_results)
                if a and a.get("can_extract") in ("NO", "PARTIAL")
            ]

            await self.notifier.send(
                f"*Phase 1.3-1.4* — Audited {len(findings)} findings, "
                f"{len(fixes_needed)} need fixes"
            )

            modifications = []
            for finding, audit in fixes_needed:
                fix_result = await self._implement_fix(case_name, finding, audit)
                if fix_result:
                    modifications.append({
                        "finding_id": finding.get("id"),
                        "file": audit.get("fix_spec", {}).get("file", "unknown"),
                        "result": fix_result,
                    })

            # Step 1.5: Extraction-only integration test
            self.state.transition(State.RUNNING_EXTRACTION)
            extraction_output, extraction_score = self._run_pipeline(case_name, extraction_only=True)
            logger.info("Extraction-only score: %s", extraction_score)

            # Have agent review the extraction results
            review_result = await self._query(
                agent_prompts.build_integration_test_prompt(case_name),
                "phase1_integration_test",
                timeout=180,
            )

            # Step 1.6: Pre-pipeline review
            modifications_summary = json.dumps(modifications, indent=2, default=str)
            review_prompt = agent_prompts.build_pre_pipeline_review_prompt(
                self.templates_dir,
                case_name,
                num_findings=len(findings),
                num_fixes=len(modifications),
                extraction_score=str(extraction_score or "unknown"),
                modifications_summary=modifications_summary[:5000],
            )
            pre_review = await self._query(review_prompt, "phase1_pre_review", timeout=180)

            # Run extraction-only regression
            regression_output, _ = self._run_pipeline("spottedinthewild", extraction_only=True)
            logger.info("Regression check output: %s", regression_output[:200])

            await self.notifier.send(
                f"*Phase 1 complete*\n"
                f"Findings: {len(findings)} | Fixes: {len(modifications)}\n"
                f"Extraction score: {extraction_score or 'unknown'}\n"
                f"Ready for pipeline run #1"
            )

            # ==========================================
            # PHASE 2: First Pipeline Run
            # ==========================================
            self.state.transition(State.RUNNING_FULL_PIPELINE)
            self._pipeline_runs += 1

            await self.notifier.send(
                f"*Phase 2* — Pipeline run #{self._pipeline_runs}/{MAX_PIPELINE_RUNS}"
            )

            pipeline_output, score = self._run_pipeline(case_name, extraction_only=False)
            self.state.transition(State.COMPARING_RESULTS)

            if score is not None:
                self.state.record_score(CycleScore(
                    iteration=1,
                    score_numeric=score,
                    score_display=f"{score:.1f}%",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
                await self.notifier.send_score_update(
                    case_name, cycle, 1, score, None, self.cost_tracker.cycle_cost,
                )

                # If already at target, skip to Phase 5
                if score >= self.config.cycles.target_score:
                    logger.info("Target reached on first run: %.1f%%", score)
                    await self._phase5_approval(case_name, cycle, score, branch)
                    return

            first_score = score

            # ==========================================
            # PHASE 3: Post-Run Gap Analysis
            # ==========================================
            self.state.transition(State.ANALYZING_GAPS)

            await self.notifier.send(
                f"*Phase 3* — Post-run gap analysis\n"
                f"Score: {score or 'unknown'}% | Target: {self.config.cycles.target_score}%"
            )

            # Get the comparator output for gap details
            comparison_output, _ = self._run_comparison(case_name)

            # Identify remaining gaps
            remaining_gaps = self._identify_gaps(case_name, comparison_output)

            if remaining_gaps:
                # Step 3.1: Per-gap deep analysis
                gap_analyses = []
                for finding, gap_type in remaining_gaps:
                    gap_result = await self._query(
                        agent_prompts.build_gap_analysis_prompt(
                            self.templates_dir, finding, case_name, gap_type
                        ),
                        f"phase3_gap_{finding.get('id', '?')}",
                        timeout=180,
                    )
                    gap_json = self._extract_json(gap_result.result) if gap_result.success else None
                    gap_analyses.append((finding, gap_json or {"actual_gap_type": gap_type}))

                # Step 3.2: Implement + unit test each fix
                self.state.transition(State.IMPLEMENTING_FIXES)
                for finding, gap_analysis in gap_analyses:
                    if gap_analysis.get("fix_spec"):
                        fix_prompt = agent_prompts.build_post_fix_prompt(
                            finding, gap_analysis, case_name
                        )
                        await self._query(
                            fix_prompt,
                            f"phase3_fix_{finding.get('id', '?')}",
                            timeout=180,
                        )

                # Step 3.3: Extraction-only retest
                self.state.transition(State.RUNNING_EXTRACTION)
                retest_output, retest_score = self._run_pipeline(case_name, extraction_only=True)
                logger.info("Post-fix extraction score: %s", retest_score)

                await self.notifier.send(
                    f"*Phase 3 complete*\n"
                    f"Gaps analyzed: {len(remaining_gaps)}\n"
                    f"Extraction retest: {retest_score or 'unknown'}%"
                )

            # ==========================================
            # PHASE 4: Final Pipeline Run
            # ==========================================
            if self._pipeline_runs < MAX_PIPELINE_RUNS:
                self.state.transition(State.RUNNING_FULL_PIPELINE)
                self._pipeline_runs += 1

                await self.notifier.send(
                    f"*Phase 4* — Final pipeline run #{self._pipeline_runs}/{MAX_PIPELINE_RUNS}"
                )

                pipeline_output, score = self._run_pipeline(case_name, extraction_only=False)
                self.state.transition(State.COMPARING_RESULTS)

                if score is not None:
                    self.state.record_score(CycleScore(
                        iteration=2,
                        score_numeric=score,
                        score_display=f"{score:.1f}%",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    ))
                    await self.notifier.send_score_update(
                        case_name, cycle, 2, score, first_score,
                        self.cost_tracker.cycle_cost,
                    )

            # Run regression
            self.state.transition(State.RUNNING_REGRESSION)
            regression_output, _ = self._run_pipeline("spottedinthewild", extraction_only=True)

            # ==========================================
            # PHASE 5: Approval & Commit
            # ==========================================
            final_score = score or first_score or 0.0
            await self._phase5_approval(case_name, cycle, final_score, branch)

        except InvalidTransition as e:
            logger.error("Invalid state transition: %s", e)
            await self.notifier.send_error(case_name, str(e))
            self.state.set_error(str(e))
        except BudgetExceeded as e:
            logger.error("Budget exceeded: %s", e)
            await self.notifier.send_error(case_name, str(e))
            self.state.set_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error in cycle")
            await self.notifier.send_error(case_name, str(e))
            self.state.set_error(str(e))

    # --- Sub-phase helpers ---

    async def _audit_findings(
        self, case_name: str, findings: list[dict]
    ) -> list[dict | None]:
        """Phase 1.3: Run per-finding audit queries."""
        results = []
        for i, finding in enumerate(findings):
            logger.info(
                "Auditing finding %d/%d: %s",
                i + 1, len(findings), finding.get("id", "?"),
            )
            await self.notifier.send(
                f"Auditing {finding.get('id', '?')}/{len(findings)}: "
                f"{finding.get('description', '')[:60]}"
            )

            audit_prompt = agent_prompts.build_finding_audit_prompt(
                self.templates_dir, finding, case_name
            )
            result = await self._query(
                audit_prompt,
                f"phase1_audit_{finding.get('id', '?')}",
                timeout=180,
            )

            audit_json = self._extract_json(result.result) if result.success else None
            results.append(audit_json)

        return results

    async def _implement_fix(
        self, case_name: str, finding: dict, audit: dict
    ) -> str | None:
        """Phase 1.4: Implement and unit-test a fix for one finding."""
        logger.info("Implementing fix for %s", finding.get("id", "?"))

        fix_prompt = agent_prompts.build_fix_implementation_prompt(
            self.templates_dir, finding, audit, case_name
        )
        result = await self._query(
            fix_prompt,
            f"phase1_fix_{finding.get('id', '?')}",
            timeout=300,
        )

        if result.success:
            return result.result[:500]
        else:
            logger.warning("Fix failed for %s: %s", finding.get("id"), result.error)
            return None

    async def _phase5_approval(
        self, case_name: str, cycle: int, score: float, branch: str
    ) -> None:
        """Phase 5: Approval gate and commit."""
        self.state.transition(State.AWAITING_APPROVAL)

        scores = self.state.current.scores
        score_history = " -> ".join(
            s.get("score_display", "?") for s in scores
        ) if scores else f"{score:.1f}%"

        await self.notifier.send_approval_request(
            case_name=case_name,
            cycle=cycle,
            score=score,
            prev_score=scores[0].get("score_numeric") if len(scores) > 1 else None,
            cost_usd=self.cost_tracker.cycle_cost,
            fixes_summary=(
                f"Pipeline runs: {self._pipeline_runs}/{MAX_PIPELINE_RUNS}\n"
                f"Score progression: {score_history}\n"
                f"Total cost: ${self.cost_tracker.cycle_cost:.2f}"
            ),
        )

        decision = await self.notifier.poll_for_approval(
            state_file=self.state.state_file,
            poll_interval=self.config.approval.poll_interval,
            timeout=self.config.approval.approval_timeout,
        )

        if decision == "approve":
            self.state.transition(State.COMMITTING)
            if self.config.git.auto_commit:
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(self.config.target.local_path),
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "commit", "-m",
                     f"training: cycle {cycle} improvements for {case_name} ({score:.1f}%)"],
                    cwd=str(self.config.target.local_path),
                    capture_output=True,
                )
            await self.notifier.send_complete(case_name, score, self.cost_tracker.cycle_cost)
            self.state.reset()
        elif decision == "reject":
            logger.info("Rejected — reverting changes")
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=str(self.config.target.local_path),
                capture_output=True,
            )
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=str(self.config.target.local_path),
                capture_output=True,
            )
            self.state.reset()
        else:
            logger.info("Skipped — moving on")
            self.state.reset()

    # --- Utility methods ---

    def _load_answer_key(self, answer_key_path: str) -> list[dict]:
        """Load findings from answer_key.json."""
        full_path = self.config.target.local_path / answer_key_path
        if not full_path.exists():
            logger.warning("Answer key not found: %s", full_path)
            return []
        try:
            data = json.loads(full_path.read_text())
            return data.get("expected_findings", [])
        except (json.JSONDecodeError, TypeError) as e:
            logger.error("Failed to parse answer key: %s", e)
            return []

    def _identify_gaps(
        self, case_name: str, comparison_output: str
    ) -> list[tuple[dict, str]]:
        """Parse comparison output to find remaining gaps matched to findings."""
        findings = self._load_answer_key(f"improvement/cases/{case_name}/answer_key.json")
        gaps = []

        for finding in findings:
            finding_id = finding.get("id", "")
            # Check if this finding's search terms appear in comparison output as a gap
            for term in finding.get("search_terms", []):
                if term.lower() not in comparison_output.lower():
                    # Determine gap type from comparison output
                    gap_type = "EXTRACTION_GAP"  # default
                    if f"{finding_id}" in comparison_output:
                        if "AGENT_GAP" in comparison_output:
                            gap_type = "AGENT_GAP"
                        elif "REPORT_GAP" in comparison_output:
                            gap_type = "REPORT_GAP"
                    gaps.append((finding, gap_type))
                    break  # one gap per finding is enough

        return gaps

    def _record_cost(self, case_name: str, cycle: int, phase: str, cost_usd: float) -> None:
        """Record a cost entry."""
        self.cost_tracker.record(CostEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            case_name=case_name,
            cycle=cycle,
            phase=phase,
            cost_usd=cost_usd,
        ))
        self.state.record_cost(cost_usd)

    def _parse_score(self, response: str) -> float | None:
        """Try to extract a score percentage from pipeline/comparator output."""
        import re

        patterns = [
            r"(\d+\.?\d*)\s*%",
            r"(\d+)/(\d+)\s*\((\d+\.?\d*)%\)",
        ]
        for pattern in patterns:
            match = re.search(pattern, response)
            if match:
                groups = match.groups()
                return float(groups[-1]) if len(groups) > 1 else float(groups[0])
        return None

    # --- CLI commands ---

    async def resume(self) -> None:
        """Resume from saved state."""
        if not self.state.can_resume():
            logger.info("No resumable state. Status: %s", self.state.status.value)
            return

        current = self.state.current
        logger.info(
            "Resuming: case=%s, cycle=%d, status=%s",
            current.case_name, current.cycle, current.status,
        )

        if self.state.status == State.AWAITING_APPROVAL:
            decision = await self.notifier.poll_for_approval(
                state_file=self.state.state_file,
                poll_interval=self.config.approval.poll_interval,
            )
            logger.info("Decision: %s", decision)
        else:
            await self.run_cycle(case_name=current.case_name)

    def approve(self) -> None:
        """Manual approval from terminal."""
        if self.state.status != State.AWAITING_APPROVAL:
            logger.info("Not awaiting approval. Status: %s", self.state.status.value)
            return

        data = json.loads(self.state.state_file.read_text())
        data["status"] = "APPROVED"
        self.state.state_file.write_text(json.dumps(data, indent=2))
        logger.info("Approved manually.")

    def status(self) -> None:
        """Print current status."""
        current = self.state.current
        print(f"Status:         {current.status}")
        print(f"Case:           {current.case_name or 'none'}")
        print(f"Cycle:          {current.cycle}")
        print(f"Iteration:      {current.iteration}")
        print(f"Cost:           ${current.cost_usd:.2f}")
        print(f"Session:        {current.session_id or 'none'}")
        print(f"Pipeline runs:  {self._pipeline_runs}/{MAX_PIPELINE_RUNS}")
        if current.last_error:
            print(f"Error:          {current.last_error}")
        if current.scores:
            print(f"Scores:         {[s.get('score_display', '?') for s in current.scores]}")
        print(f"\nTotal cost:     ${self.cost_tracker.total_cost:.2f}")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ARGUS Training Agent v2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    run_parser = subparsers.add_parser("run", help="Run a training cycle")
    run_parser.add_argument("--case", required=True, help="Case name to train on")
    run_parser.add_argument("--dry-run", action="store_true", help="Initialize without running")
    run_parser.add_argument("--config", default="config.yaml", help="Config file path")

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume from saved state")
    resume_parser.add_argument("--config", default="config.yaml", help="Config file path")

    # approve
    approve_parser = subparsers.add_parser("approve", help="Manually approve pending changes")
    approve_parser.add_argument("--config", default="config.yaml", help="Config file path")

    # status
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.add_argument("--config", default="config.yaml", help="Config file path")

    # bot
    bot_parser = subparsers.add_parser("bot", help="Run Telegram approval bot")
    bot_parser.add_argument("--config", default="config.yaml", help="Config file path")

    args = parser.parse_args()

    config = load_config(
        config_path=args.config,
        project_root=Path.cwd(),
    )
    setup_logging(config.logging.level)
    orchestrator = Orchestrator(config)

    if args.command == "run":
        asyncio.run(orchestrator.run_cycle(
            case_name=args.case,
            dry_run=getattr(args, "dry_run", False),
        ))
    elif args.command == "resume":
        asyncio.run(orchestrator.resume())
    elif args.command == "approve":
        orchestrator.approve()
    elif args.command == "status":
        orchestrator.status()
    elif args.command == "bot":
        bot = TelegramApprovalBot(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
            state_file=config.state_dir / "agent_state.json",
        )
        asyncio.run(bot.run())


if __name__ == "__main__":
    main()
