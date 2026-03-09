# Finding Audit — Does ARGUS Extract This?

You are auditing a single finding from a forensic challenge walkthrough to determine if ARGUS can currently extract it.

## The Finding

- **ID**: {finding_id}
- **Description**: {description}
- **Category**: {category}
- **Evidence file**: {evidence_file} (type: {evidence_type})
- **Search terms**: {search_terms}
- **Search mode**: {search_mode}

## Instructions

### Step 1: Read the ARGUS parser for this evidence type

Read the ENTIRE parser file — not just function signatures:

| Evidence Type | Parser File |
|---|---|
| pcap | `src/argus/parsers/pcap.py` |
| memory | `src/argus/parsers/memory.py` |
| pe | `src/argus/parsers/pe.py` |
| evtx | `src/argus/parsers/evtx.py` |
| registry | `src/argus/parsers/registry.py` |
| prefetch | `src/argus/parsers/prefetch.py` |
| disk | `src/argus/parsers/disk.py` |
| iis | `src/argus/parsers/iis.py` |
| xlsx | `src/argus/parsers/xlsx.py` |
| browser | `src/argus/parsers/browser.py` |

### Step 2: Read the extraction functions

- Read `src/argus/extractors/forensic_extractor.py` — focus on how this evidence type is handled.
- Read the relevant extraction stages (`src/argus/extraction/stage1_fields.py` through `stage7_assembly.py`) that process this data type.

### Step 3: Search for the capability

For EACH search term from the finding:
- Grep the parser code for the term or related patterns
- Grep the extractor code for the term or related patterns
- Check if the parser outputs the data type this finding requires
- Trace the data flow: evidence file -> parser -> extractor -> stage output -> final extraction JSON

### Step 4: Determine extractability

Can ARGUS currently extract this finding? Classify as:

- **YES**: The data path exists, search terms would appear in extraction output. PROVE IT — show the exact function, line number, and output field.
- **PARTIAL**: Some search terms would match but not all. Explain what's missing.
- **NO**: The parser/extractor doesn't handle this data. Explain what's missing.

### Step 5: If NO or PARTIAL, define the fix

Be surgical and specific:
1. Which file needs to change? (exact path)
2. Which function needs to change? (exact name)
3. What code should be added/modified? (describe the logic, not pseudocode)
4. What would the parser output look like AFTER the fix?
5. Would the answer key search terms match that output? (verify explicitly)

## Output Format

Respond with a JSON object:

```json
{{
  "finding_id": "{finding_id}",
  "can_extract": "YES|PARTIAL|NO",
  "confidence": "HIGH|MEDIUM|LOW",
  "evidence_examined": [
    {{
      "file": "src/argus/parsers/pcap.py",
      "relevant_functions": ["parse_connections", "extract_dns"],
      "relevant_lines": "L45-L82"
    }}
  ],
  "data_path_trace": "evidence/capture.pcapng -> PcapParser.parse() -> connections list -> stage1_fields -> extraction JSON 'network_connections' field",
  "search_term_coverage": {{
    "term1": {{"found": true, "location": "parser output field 'dst_ip'"}},
    "term2": {{"found": false, "reason": "parser doesn't extract SMB share names"}}
  }},
  "fix_required": true,
  "fix_spec": {{
    "file": "src/argus/parsers/pcap.py",
    "function": "parse_connections",
    "change_description": "Add SMB/CIFS share name extraction from SMB2 tree connect packets",
    "expected_output_field": "smb_shares",
    "expected_output_sample": "IPC$, C$, ADMIN$",
    "search_terms_would_match": true
  }}
}}
```

## Rules

- Do NOT run any pipeline commands (`runner.py run`, `runner.py regression`, `python -m argus`, `argus init`, `argus analyze`)
- Do NOT modify any files — READ and ANALYZE only
- Be specific: cite file paths, function names, line numbers
- If you're unsure whether the data path exists, err on the side of NO — it's better to implement a fix that turns out to be unnecessary than to miss a gap
