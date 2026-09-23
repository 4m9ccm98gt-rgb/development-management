# MAIN IMPLEMENTATION

Implement the agreed TaskSpec in this isolated worktree. Inspect the relevant
code as needed. Do not start separate reviewers or sub-agents. Independent
Verification and Final Review are owned by the Orchestrator.

## TaskSpec
{{TASK}}

Preserve scope, existing changes, secrets and business data. Do not commit,
push, switch branches, reset, stash, rebase, BUILD, UPDATE or DEPLOY. Do not
change the source repository. Do not weaken tests or acceptance conditions.
Report changes and unresolved issues. If implementation is blocked, include
the exact standalone line `IMPLEMENTATION_STATUS: BLOCKED` and its reason.
