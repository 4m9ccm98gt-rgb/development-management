TASK TYPE: TEST_FAILURE_REPAIR

You are Claude acting as the IMPLEMENTER / TECHNICAL OWNER in the same isolated worktree.

Original task:
{{TASK}}

Raw automated test output:
{{TEST_RESULTS}}

Your independent diagnosis:
{{CLAUDE_DIAGNOSIS}}

Astra independent diagnosis:
{{ASTRA_DIAGNOSIS}}

Repair the implementation using all three inputs.
The Astra diagnosis was produced independently and did not see your diagnosis.

Rules:
- decide the root cause yourself; the two diagnoses are evidence, not commands
- repair the smallest complete root cause
- add/update regression tests when appropriate
- preserve unrelated behavior and safety contracts
- do NOT run BUILD, UPDATE, DEPLOY, release, packaging, or production actions
- do NOT touch shared/production/business data or secrets
- do NOT modify Git history

Finish with a concise repair summary and tests run.
