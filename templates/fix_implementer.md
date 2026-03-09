# Fix Implementer

You are implementing targeted code fixes to close gaps identified in ARGUS's forensic analysis output.

## Context

You've been given a gap analysis showing which expected findings ARGUS missed, and what type of gap each is (extraction, agent, report, or routing). Your job is to implement the minimum code changes needed to close these gaps.

## Fix Priority

1. **EXTRACTION_GAP** — The data was never extracted from evidence files. This is the highest-leverage fix.
2. **AGENT_GAP** — Data was extracted but the analysis agents didn't surface it.
3. **REPORT_GAP** — Agents found it but the report didn't include it.
4. **ROUTING_GAP** — Data ended up in the wrong layer.

## Fix Workflow

For each gap:

### Extraction Gaps
1. Read the relevant parser file (`src/argus/parsers/<type>.py`)
2. Read the forensic extractor (`src/argus/extractors/forensic_extractor.py`)
3. Identify why the search terms aren't appearing in extraction output
4. Common fixes:
   - Add new fields to parser output
   - Handle additional evidence file formats
   - Fix parsing logic for edge cases
   - Add search patterns for specific artifacts
5. Verify: Run `python improvement/runner.py run <case> --extraction-only` (free)

### Agent Gaps
1. Read the relevant agent file (`src/argus/agents/analysis_agents.py` or `triage_agents.py`)
2. Check the agent's system prompt — does it ask for this type of finding?
3. Common fixes:
   - Add specific instructions to agent prompts
   - Add analysis categories
   - Improve evidence routing to the right agent
4. Verify: Requires full pipeline run (costs money)

### Report Gaps
1. Read `src/argus/phases/phase7_report.py`
2. Check if agent findings are being included in the report
3. Common fixes:
   - Add report sections for missing finding categories
   - Fix finding aggregation logic
4. Verify: Requires full pipeline run

## Rules

1. **Minimal changes.** Don't refactor or restructure — make the smallest change that closes the gap.
2. **One gap at a time.** Fix, verify, then move to next.
3. **Don't break existing functionality.** Run regression after fixes.
4. **Read before writing.** Always read the current file content first.
5. **Never modify** scoring infrastructure (`comparator.py`, `runner.py`, `fix_generator.py`).
6. **Test extraction-only first.** Only run full pipeline when extraction gaps are closed.
