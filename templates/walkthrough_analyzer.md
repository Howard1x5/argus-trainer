# Walkthrough Analyzer

You are analyzing a CyberDefenders forensic challenge walkthrough to extract key findings that ARGUS should detect.

## Task

Given a walkthrough URL or content, extract every forensic finding and produce a structured analysis.

## What to Extract

For each finding in the walkthrough:
1. **What was found** — the specific artifact, IOC, or behavioral indicator
2. **Where it was found** — which evidence file, log entry, or memory region
3. **Why it matters** — what it indicates about the incident (lateral movement, persistence, exfil, etc.)
4. **Search terms** — exact strings that would appear in ARGUS output if correctly detected (IP addresses, file names, hashes, process names, command-line arguments, registry keys, MITRE technique IDs)

## Output Format

Produce a JSON structure following the answer key schema:

```json
{
  "findings": [
    {
      "id": "F01",
      "category": "<category>",
      "description": "<what was found and why it matters>",
      "search_terms": ["<exact_string_1>", "<exact_string_2>"],
      "search_mode": "ALL or ANY",
      "required": true,
      "points": 10,
      "source_evidence": "<which evidence file contains this>",
      "walkthrough_section": "<which section of the walkthrough describes this>"
    }
  ]
}
```

## Categories

Use these categories (matching ARGUS comparator):
- `process` — process execution, command-line args, parent-child relationships
- `network` — IP addresses, domains, URLs, DNS queries, connections
- `malware` — file hashes, malicious files, payloads, shellcode
- `user` — user accounts, authentication events, privilege escalation
- `injection` — process injection, DLL injection, code injection
- `persistence` — registry keys, scheduled tasks, services, startup items
- `exfiltration` — data theft, staging, C2 communication
- `lateral_movement` — RDP, PsExec, WMI, SMB lateral movement
- `credential_access` — credential dumping, mimikatz, pass-the-hash
- `mitre` — MITRE ATT&CK technique IDs (bonus findings)

## Search Mode Guidelines

- Use `ALL` when the finding requires multiple terms to be specific (e.g., a process name AND a command-line argument)
- Use `ANY` when any single term uniquely identifies the finding (e.g., a unique hash or IP address)

## Point Values

- Core findings (required): 10 points each
- Important but less critical: 5 points
- MITRE technique IDs: 5 points each (bonus)
- Optional/enrichment findings: 3-5 points

## Important

- Be precise with search terms. Use exact strings that would appear in parsed output.
- Case-insensitive matching is used, so don't worry about capitalization.
- Include both the raw IOC and common representations (e.g., both IP and domain if related).
- Cross-reference multiple walkthrough sources when available for accuracy.
