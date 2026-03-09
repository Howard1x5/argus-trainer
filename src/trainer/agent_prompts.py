"""Prompt builders for the v2 training loop.

Each function builds a focused micro-query for a specific step.
All prompts are transport-agnostic (work with CLI or SDK).
"""

from __future__ import annotations

import json
from pathlib import Path


def _load_template(templates_dir: Path, name: str) -> str:
    """Load a template file and return its content."""
    path = templates_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return path.read_text()


# --- Template loaders ---

def system_prompt(templates_dir: Path) -> str:
    return _load_template(templates_dir, "system_prompt.md")


def walkthrough_analyzer(templates_dir: Path) -> str:
    return _load_template(templates_dir, "walkthrough_analyzer.md")


def answer_key_builder(templates_dir: Path) -> str:
    return _load_template(templates_dir, "answer_key_builder.md")


def fix_implementer(templates_dir: Path) -> str:
    return _load_template(templates_dir, "fix_implementer.md")


def finding_auditor(templates_dir: Path) -> str:
    return _load_template(templates_dir, "finding_auditor.md")


def deep_gap_analyzer(templates_dir: Path) -> str:
    return _load_template(templates_dir, "deep_gap_analyzer.md")


def pre_pipeline_review(templates_dir: Path) -> str:
    return _load_template(templates_dir, "pre_pipeline_review.md")


# --- Phase 1: Walkthrough Dissection ---

def build_fetch_walkthrough_prompt(case_name: str, walkthrough_url: str) -> str:
    """Step 1.1: Fetch and return all walkthrough content."""
    if walkthrough_url:
        source = f"Fetch the walkthrough from: {walkthrough_url}"
    else:
        source = (
            f"Search for the CyberDefenders '{case_name}' challenge walkthrough using WebSearch. "
            f"Find the most detailed walkthrough available. Try multiple search queries if needed."
        )

    return f"""## Fetch Walkthrough — {case_name}

{source}

### Task
1. Retrieve the full walkthrough content
2. If searching, try queries like:
   - "CyberDefenders {case_name} walkthrough"
   - "CyberDefenders {case_name} writeup"
   - "CyberDefenders {case_name} solution"
3. Extract ALL forensic findings, IOCs, and analysis steps
4. Return the complete walkthrough content — do not summarize or skip sections

### Output
Return the full walkthrough text. Include every finding, every IOC, every analysis step."""


def build_answer_key_prompt(
    templates_dir: Path,
    case_name: str,
    walkthrough_content: str,
) -> str:
    """Step 1.2: Build master finding list from walkthrough content."""
    analyzer_template = walkthrough_analyzer(templates_dir)
    builder_template = answer_key_builder(templates_dir)

    return f"""## Build Answer Key — {case_name}

### Walkthrough Content
{walkthrough_content[:15000]}

### Instructions

Follow BOTH of these templates to extract findings and build the answer key:

---
{analyzer_template}
---
{builder_template}
---

### Important
- Extract EVERY finding with sub-atomic detail
- For each finding, include:
  - Exact IOC/artifact/behavior
  - Which evidence file contains it
  - What tool/technique reveals it
  - Search terms that would match in ARGUS output
- Write the answer key to: `improvement/cases/{case_name}/answer_key.json`
- Create the directory if it doesn't exist: `mkdir -p improvement/cases/{case_name}`

### Output
Write the answer_key.json file and confirm the number of findings and total points."""


def build_finding_audit_prompt(
    templates_dir: Path,
    finding: dict,
    case_name: str,
) -> str:
    """Step 1.3: Per-finding deep audit — can ARGUS extract this?"""
    template = finding_auditor(templates_dir)

    return template.format(
        finding_id=finding.get("id", "?"),
        description=finding.get("description", ""),
        category=finding.get("category", ""),
        evidence_file=finding.get("source_evidence", "unknown"),
        evidence_type=_infer_evidence_type(finding.get("source_evidence", "")),
        search_terms=json.dumps(finding.get("search_terms", [])),
        search_mode=finding.get("search_mode", "ANY"),
    )


def build_fix_implementation_prompt(
    templates_dir: Path,
    finding: dict,
    audit_result: dict,
    case_name: str,
) -> str:
    """Step 1.4: Implement and unit-test a fix for a single finding."""
    fix_spec = audit_result.get("fix_spec", {})
    evidence_file = finding.get("source_evidence", "unknown")
    search_terms = finding.get("search_terms", [])

    return f"""## Implement Fix — {finding.get('id', '?')}: {finding.get('description', '')[:80]}

### Audit Result
The finding audit determined ARGUS cannot extract this finding.

**Fix specification:**
- File: `{fix_spec.get('file', 'unknown')}`
- Function: `{fix_spec.get('function', 'unknown')}`
- Change: {fix_spec.get('change_description', 'unknown')}
- Expected output field: `{fix_spec.get('expected_output_field', 'unknown')}`

### Task

1. **Read the target file** — read the ENTIRE file, not just the function
2. **Implement the fix** — make the minimal change described above
3. **Unit test the fix** — run the specific parser on the evidence file:

```bash
cd /opt/argus && .venv/bin/python -c "
from argus.parsers.{_infer_parser_module(evidence_file)} import {_infer_parser_class(evidence_file)}
p = {_infer_parser_class(evidence_file)}()
result = p.parse('improvement/cases/{case_name}/{evidence_file}')
import json
# Search for expected terms
terms = {json.dumps(search_terms)}
for term in terms:
    found = any(term.lower() in json.dumps(r, default=str).lower() for r in (result if isinstance(result, list) else [result]))
    print(f'  {{term}}: {{'FOUND' if found else 'MISSING'}}')
print(f'Total records: {{len(result) if isinstance(result, list) else 1}}')
"
```

4. **Verify**: Do ALL search terms appear in the parser output?
   - YES -> Fix confirmed. Report success.
   - NO -> Analyze WHY:
     - What does the raw evidence actually contain? (try: `strings`, `hexdump -C | head`)
     - Is the data there but in a different format?
     - Does the parser need a different approach?
     - Adjust the fix and re-test.

### Rules
- Do NOT run `runner.py` or any pipeline command
- Make MINIMAL changes — don't refactor surrounding code
- Read the file BEFORE editing
- If the fix fails after 2 adjustments, report what you found and move on"""


def build_integration_test_prompt(case_name: str) -> str:
    """Step 1.5: Review extraction-only results (run by orchestrator, not agent)."""
    return f"""## Integration Test Review — {case_name}

The orchestrator has run extraction-only for this case. The results are at:
`improvement/cases/{case_name}/extractions/`

### Task

1. Read the answer key: `improvement/cases/{case_name}/answer_key.json`
2. Read ALL extraction output files in `improvement/cases/{case_name}/extractions/`
3. For EACH finding in the answer key:
   - Search for the finding's search terms in the extraction output
   - Report: FOUND or MISSING
4. Calculate the extraction coverage: (found / total) as percentage

### Output

Report as JSON:
```json
{{
  "total_findings": 12,
  "found_in_extraction": 10,
  "missing_from_extraction": 2,
  "extraction_coverage_pct": 83.3,
  "missing_findings": [
    {{"id": "F05", "description": "...", "reason": "parser doesn't handle this format"}}
  ]
}}
```"""


def build_pre_pipeline_review_prompt(
    templates_dir: Path,
    case_name: str,
    num_findings: int,
    num_fixes: int,
    extraction_score: str,
    modifications_summary: str,
) -> str:
    """Step 1.6: Pre-pipeline coherence review."""
    template = pre_pipeline_review(templates_dir)

    return template.format(
        case_name=case_name,
        num_findings=num_findings,
        num_fixes=num_fixes,
        extraction_score=extraction_score,
        modifications_summary=modifications_summary,
    )


# --- Phase 3: Post-Pipeline Gap Analysis ---

def build_gap_analysis_prompt(
    templates_dir: Path,
    finding: dict,
    case_name: str,
    gap_type: str,
) -> str:
    """Step 3.1: Per-gap deep analysis after pipeline run."""
    template = deep_gap_analyzer(templates_dir)

    return template.format(
        finding_id=finding.get("id", "?"),
        description=finding.get("description", ""),
        category=finding.get("category", ""),
        search_terms=json.dumps(finding.get("search_terms", [])),
        gap_type=gap_type,
        points=finding.get("points", 0),
        case_name=case_name,
    )


def build_post_fix_prompt(
    finding: dict,
    gap_analysis: dict,
    case_name: str,
) -> str:
    """Step 3.2: Implement fix for a post-pipeline gap."""
    fix_spec = gap_analysis.get("fix_spec", {})
    search_terms = finding.get("search_terms", [])

    return f"""## Post-Pipeline Fix — {finding.get('id', '?')}: {finding.get('description', '')[:80]}

### Gap Analysis Result
- Gap type: {gap_analysis.get('actual_gap_type', 'unknown')}
- Failure point: {gap_analysis.get('failure_point', {}).get('detail', 'unknown')}
- Root cause: {gap_analysis.get('root_cause', 'unknown')}

### Fix Specification
- File: `{fix_spec.get('file', 'unknown')}`
- Function: `{fix_spec.get('function', 'unknown')}`
- Change: {fix_spec.get('change_description', 'unknown')}

### Task
1. Read the target file
2. Implement the fix
3. Unit test: run the specific parser and verify search terms {json.dumps(search_terms)} appear in output
4. If the fix is for an AGENT_GAP or REPORT_GAP, read+modify the agent/report file and explain what changed

### Rules
- Do NOT run `runner.py` or any pipeline command
- Minimal changes only
- Read before editing"""


# --- Helpers ---

def _infer_evidence_type(evidence_file: str) -> str:
    """Infer evidence type from file extension."""
    ext_map = {
        ".pcap": "pcap", ".pcapng": "pcap",
        ".raw": "memory", ".mem": "memory", ".dmp": "memory", ".vmem": "memory",
        ".evtx": "evtx",
        ".exe": "pe", ".dll": "pe", ".sys": "pe",
        ".reg": "registry",
        ".pf": "prefetch",
        ".xlsx": "xlsx", ".xls": "xlsx", ".csv": "xlsx",
        ".log": "iis",
        ".E01": "disk", ".dd": "disk",
    }
    for ext, etype in ext_map.items():
        if evidence_file.lower().endswith(ext.lower()):
            return etype
    return "unknown"


def _infer_parser_module(evidence_file: str) -> str:
    """Infer parser module name from evidence file."""
    etype = _infer_evidence_type(evidence_file)
    return etype if etype != "unknown" else "generic"


def _infer_parser_class(evidence_file: str) -> str:
    """Infer parser class name from evidence file."""
    etype = _infer_evidence_type(evidence_file)
    class_map = {
        "pcap": "PcapParser",
        "memory": "MemoryParser",
        "evtx": "EvtxParser",
        "pe": "PeParser",
        "registry": "RegistryParser",
        "prefetch": "PrefetchParser",
        "xlsx": "XlsxParser",
        "iis": "IisParser",
        "disk": "DiskParser",
        "browser": "BrowserParser",
    }
    return class_map.get(etype, "GenericParser")
