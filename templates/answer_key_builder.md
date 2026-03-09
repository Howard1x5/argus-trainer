# Answer Key Builder

You are building an answer key JSON file for an ARGUS training case from walkthrough content.

## Input

You'll receive walkthrough content (from a CyberDefenders challenge walkthrough) containing:
- Challenge questions and answers
- Evidence file descriptions
- Step-by-step forensic analysis
- IOCs discovered
- Attack timeline

## Output

Generate a complete `answer_key.json` following this exact schema:

```json
{
  "case_name": "<lowercase_no_spaces>",
  "source": "CyberDefenders",
  "difficulty": "<easy|medium|hard>",
  "evidence_files": [
    {
      "path": "evidence/<filename>",
      "type": "<evtx|memory|pcap|xlsx|iis|pe|disk|registry|prefetch|browser>"
    }
  ],
  "expected_findings": [
    {
      "id": "F01",
      "category": "<category>",
      "description": "<clear description of what should be found>",
      "search_terms": ["<exact_term_1>", "<exact_term_2>"],
      "search_mode": "ALL|ANY",
      "required": true|false,
      "points": 10
    }
  ],
  "total_possible_points": "<sum of all points>"
}
```

## Guidelines for Search Terms

Search terms must be exact strings that would appear in ARGUS's parsed output:

- **IP addresses**: Use the exact IP (e.g., `"192.168.1.100"`)
- **Domains**: Use the full domain (e.g., `"malicious.example.com"`)
- **File names**: Use the exact file name (e.g., `"mimikatz.exe"`)
- **Hashes**: Use the full hash value
- **Process names**: Use the process name as it appears in logs
- **Registry keys**: Use the key path or key name
- **MITRE IDs**: Use the technique ID (e.g., `"T1059.001"`)
- **Command-line args**: Use distinctive fragments of the command line
- **Timestamps**: Generally avoid — too format-dependent

## Category Assignment

Each finding gets exactly one primary category:
- `process` — Process execution artifacts
- `network` — Network connections, DNS, traffic
- `malware` — Malicious files, payloads
- `user` — Account activity, authentication
- `injection` — Process/code injection techniques
- `persistence` — Persistence mechanisms
- `exfiltration` — Data theft, C2 traffic
- `lateral_movement` — Lateral movement techniques
- `credential_access` — Credential theft
- `mitre` — MITRE ATT&CK technique mapping (bonus)

## Point Values

- **Required core findings**: 10 points — key IOCs, critical processes, main attack chain
- **Important supporting findings**: 5 points — supporting evidence, secondary indicators
- **MITRE technique mappings**: 5 points — bonus for ATT&CK technique identification
- **Optional enrichment**: 3 points — nice-to-have context

## Quality Checks

Before finalizing:
1. Verify `total_possible_points` matches the sum of all finding points
2. Ensure finding IDs are sequential (F01, F02, ...)
3. Confirm search terms are specific enough to avoid false positives
4. Verify search mode is appropriate (ALL for multi-term, ANY for single unique identifiers)
5. Check that evidence file types match actual files in the case
