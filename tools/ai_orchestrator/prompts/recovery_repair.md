# RECOVERY REPAIR

Apply the smallest repair supported by the diagnosis. Independent Verification
will run afterward. Do not start sub-agents or spend a call on self-review.
Do not repeat an ineffective previous repair. Preserve TaskSpec and tests;
do not weaken acceptance conditions merely to make Verification pass.
Do not commit, push, switch branches, reset, stash, rebase, BUILD, UPDATE or
DEPLOY. Work only in this isolated worktree; protect secrets and business data.
Report the actual changes. If blocked, emit the standalone line
`IMPLEMENTATION_STATUS: BLOCKED` and explain why.

## TaskSpec
{{TASK}}
## Failure
{{FAILURE}}
## Diagnosis
{{DIAGNOSIS}}
## Iteration history
{{HISTORY}}
