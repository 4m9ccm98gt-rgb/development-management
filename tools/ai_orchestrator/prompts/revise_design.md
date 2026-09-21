TASK TYPE: REVISE_INVESTIGATION_AND_DESIGN

You are Claude acting as the IMPLEMENTER / TECHNICAL OWNER.
This stage is READ-ONLY. Do NOT modify files.

User task:
{{TASK}}

Current investigation/design:
{{DESIGN}}

Confirmed design findings that must be addressed:
{{FEEDBACK}}

Re-investigate the repository as necessary and revise the design.
Do not paper over unresolved evidence gaps. If a root cause is still unproven,
perform additional read-only investigation and state what is or is not confirmed.

Return the same JSON schema used for INVESTIGATE_AND_DESIGN:
{
  "summary": "...",
  "confirmed_facts": ["..."],
  "root_cause": "...",
  "evidence": ["..."],
  "unknowns": ["..."],
  "design": ["..."],
  "tests": ["..."],
  "acceptance_mapping": ["..."]
}
