# Pre-Pipeline Review

You are reviewing all modifications made during the walkthrough dissection phase BEFORE a pipeline run.

## Context

- **Case**: {case_name}
- **Findings audited**: {num_findings}
- **Fixes implemented**: {num_fixes}
- **Extraction-only score**: {extraction_score}

## Modifications Made

{modifications_summary}

## Instructions

### Step 1: Review each modification for correctness

For each modified file:
1. Read the CURRENT file content (post-modification)
2. Verify the change is syntactically correct (no unclosed brackets, bad indentation, missing imports)
3. Verify the change is logically correct (does it actually extract/handle what it claims?)
4. Check for side effects: does this change break the parser's handling of OTHER evidence types or findings?

### Step 2: Check for conflicts between modifications

If multiple fixes touched the same file:
- Do they conflict? (e.g., two fixes modifying the same function differently)
- Do they compose correctly? (changes to different functions in the same file should be independent)

### Step 3: Regression risk assessment

For each modified parser/extractor:
- Does this change affect how previously-passing cases are handled?
- Could this change cause existing extraction output to change format?
- Are there any hardcoded assumptions that might break?

### Step 4: Extraction-only validation

Review the extraction-only test results:
- Which findings are now captured in extraction output?
- Which findings are still missing? Why?
- Any unexpected changes in extraction output?

## Output Format

```json
{{
  "review_status": "PASS|WARN|FAIL",
  "files_reviewed": [
    {{
      "file": "src/argus/parsers/pcap.py",
      "changes_correct": true,
      "regression_risk": "LOW|MEDIUM|HIGH",
      "notes": ""
    }}
  ],
  "conflicts_found": [],
  "regression_risks": [],
  "extraction_coverage": {{
    "captured": 10,
    "missing": 2,
    "missing_details": ["F05: registry persistence key not in extraction output"]
  }},
  "recommendation": "Proceed with pipeline run|Fix issues before pipeline run",
  "confidence": "HIGH|MEDIUM|LOW"
}}
```

## Rules

- Do NOT run any pipeline commands
- Do NOT modify any files — READ and ANALYZE only
- Focus on correctness and regression risk — we only get 2 pipeline runs max
