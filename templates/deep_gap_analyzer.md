# Deep Gap Analysis — Post-Pipeline

You are analyzing a gap between the ARGUS pipeline output and a walkthrough finding AFTER a full pipeline run.

## The Gap

- **Finding ID**: {finding_id}
- **Description**: {description}
- **Category**: {category}
- **Search terms**: {search_terms}
- **Gap type from comparator**: {gap_type}
- **Points**: {points}

## ARGUS Pipeline Output Location

The full pipeline output is at:
- Extractions: `cases/{case_name}/extractions/`
- Agent analysis: `cases/{case_name}/analysis/agents/`
- Report: `cases/{case_name}/report/`

## Instructions

### Step 1: Read the ACTUAL ARGUS output

- Read ALL extraction JSON files in `cases/{case_name}/extractions/`
- Read ALL agent output files in `cases/{case_name}/analysis/agents/`
- Read the final report in `cases/{case_name}/report/`
- Search for each search term across ALL output files

### Step 2: Locate the failure point

Trace the data through each layer:

1. **Extraction layer**: Are the search terms present in any extraction JSON?
   - If NO: this is an EXTRACTION_GAP — the parser never produced this data
   - If YES: proceed to step 2

2. **Agent layer**: Did any analysis agent reference this finding?
   - If NO: this is an AGENT_GAP — agents had the data but didn't surface it
   - If YES: proceed to step 3

3. **Report layer**: Is this finding in the final report?
   - If NO: this is a REPORT_GAP — agents found it but report omitted it
   - If YES: the comparator should have matched it — check search term specificity

### Step 3: Root cause analysis

Based on the failure point:

- **EXTRACTION_GAP**: Why didn't our Phase 1 fix work? Did we miss this finding entirely? Is the evidence file format different than expected? Is the data there but in a different field/format?

- **AGENT_GAP**: Which agent should have caught this? What does its prompt say? What extraction data was available to it? Why didn't it flag this finding?

- **REPORT_GAP**: Is the report template missing a section for this category? Is the aggregation logic filtering it out?

### Step 4: Define the surgical fix

Same specificity as the finding auditor:
1. Exact file to change
2. Exact function to change
3. What the change does
4. Expected output after the change
5. Why this will close the gap

## Output Format

```json
{{
  "finding_id": "{finding_id}",
  "actual_gap_type": "EXTRACTION_GAP|AGENT_GAP|REPORT_GAP|ROUTING_GAP",
  "failure_point": {{
    "layer": "extraction|agent|report",
    "detail": "Parser output contains network connections but no SMB share names"
  }},
  "data_present_in": {{
    "extractions": false,
    "agents": false,
    "report": false
  }},
  "root_cause": "The pcap parser extracts TCP connections but does not parse SMB2 protocol tree connect responses",
  "fix_spec": {{
    "file": "src/argus/parsers/pcap.py",
    "function": "parse_connections",
    "change_description": "Add SMB2 tree connect response parsing to extract share names",
    "expected_output": "New 'smb_shares' field in connection records",
    "search_terms_would_match": true
  }},
  "confidence": "HIGH|MEDIUM|LOW"
}}
```

## Rules

- Do NOT run any pipeline commands
- Do NOT modify any files — READ and ANALYZE only
- Read ACTUAL output files, not just code — we need to see what the pipeline DID produce
- Be specific about the failure point — don't guess, trace it
