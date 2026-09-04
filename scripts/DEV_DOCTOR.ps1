<#
DEV DOCTOR - local development environment health check (Windows real machine).

Counterpart to development-management/scripts/check_standards.py:
  check_standards.py = GitHub side (does the repo meet the standard?)
  DEV_DOCTOR         = this machine side (are the tools / clones / venvs / backups OK?)

Double-click DEV_DOCTOR_CLICK_ME.cmd. Read the Summary. Paste the whole report
into ChatGPT etc. to get a diagnosis. It changes nothing (read-only).

Findings are tiered so intentional states do not bury real ones:
  [ERROR]       must fix (missing tool / repo / auth)
  [ACTION]      needs attention (uncommitted tracked changes, behind upstream,
                unexpected branch, stale backup, missing gh scope)
  [INTENTIONAL] a known/expected non-default state (active work branch, archived repo)
  [INFO]        allowed / cosmetic (no .venv yet, only untracked files, E: not mounted)

Windows PowerShell 5.1 compatible. ASCII only.
#>
param(
    [switch]$NoFetch,
    [string]$ReportPath = (Join-Path $env:USERPROFILE "DEV_DOCTOR_report.txt")
)

$ErrorActionPreference = "Continue"
$Repos = "C:\Users\suisy\Documents\Development\repos"

# repo -> its GitHub default branch
$Canon = @(
    @{ name = "development-management";              branch = "main" },
    @{ name = "next-day-setup";                      branch = "main" },
    @{ name = "inventory-reconciliation-system";     branch = "main" },
    @{ name = "beverage-inventory-ordering-system";  branch = "main" },
    @{ name = "qr-supply-ordering-system";           branch = "main" },
    @{ name = "menu-sheet-generator";                branch = "main" },
    @{ name = "call-reception-assistant";            branch = "main" },
    @{ name = "kitchen-calendar";                    branch = "main" },
    @{ name = "food-cost-calculation-system";        branch = "codex/bootstrap-invoice-reading" },
    @{ name = "hospitality-review-reply";            branch = "main" }
)
# repo -> a branch that is EXPECTED to be checked out right now (intentional work-in-progress)
$ActiveBranch = @{
    "beverage-inventory-ordering-system" = "python-desktop-migration"   # Draft PR #2, active migration
}
# repos that are archived / not actively developed (odd branch or dirtiness is not an issue)
$Archived = @("kitchen-calendar")

$script:err = 0; $script:action = 0; $script:intent = 0; $script:info = 0
$lines = New-Object System.Collections.Generic.List[string]
function L([string]$s) { [void]$lines.Add($s); Write-Host $s }
function OKV($m)    { L ("[OK]          " + $m) }
function ERRV($m)   { $script:err++;    L ("[ERROR]       " + $m) }
function ACTION($m) { $script:action++; L ("[ACTION]      " + $m) }
function INTENT($m) { $script:intent++; L ("[INTENTIONAL] " + $m) }
function INFO($m)   { $script:info++;   L ("[INFO]        " + $m) }

function FirstLine($exe, [string[]]$xargs) {
    try { (& $exe @xargs 2>&1 | Select-Object -First 1) } catch { $null }
}

L ("DEV DOCTOR   " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "   host=" + $env:COMPUTERNAME)
L ("report file: " + $ReportPath)
L "================================================================="
L ""

# ---------- toolchain ----------
L "## Toolchain"
$g = FirstLine "git" @("--version")
if ($g) { OKV ("git: " + $g) } else { ERRV "git not found in PATH" }

$pv = FirstLine "py" @("-3","--version")
if (-not $pv) { $pv = FirstLine "python" @("--version") }
if ($pv) { OKV ("python: " + $pv) } else { ERRV "python / py launcher not found" }

$gh = FirstLine "gh" @("--version")
if ($gh) {
    OKV ("gh: " + $gh)
    # Rely on the EXIT CODE of 'gh auth status', not on any substring. A revoked or
    # expired token makes gh exit non-zero even though the config still names an account.
    $auth = (& gh auth status 2>&1) -join "`n"
    $ghExit = $LASTEXITCODE
    $ghBroken = ($auth -match "(?m)^\s*X .*(Failed to log in|token .* is invalid|expired|revoked)")
    if ($ghExit -eq 0 -and -not $ghBroken) {
        $scopes = ""
        if ($auth -match "Token scopes:\s*(.+)") { $scopes = ($Matches[1].Trim()) }
        OKV ("gh auth: logged in. scopes: " + $scopes)
        if ($scopes -and ($scopes -notmatch "workflow")) {
            ACTION "gh token missing 'workflow' scope (needed to push .github/workflows). Re-run: gh auth login  (see docs\operator_runbook.md)"
        }
    } else {
        $why = if ($auth -match "invalid|expired|revoked|Failed to log in") { "token invalid / expired / revoked" } else { "not authenticated" }
        ERRV ("gh auth failed (" + $why + "). Fix: docs\operator_runbook.md section 6 (GitHub re-auth) -> run 'gh auth login'. Until fixed: PR / CI operations via gh do not work.")
    }
} else { ACTION "gh (GitHub CLI) not found. Needed for PR / CI operations." }

# git push/pull credential (Git Credential Manager) - separate from gh. All canonical
# repos are private, so a no-auth 'git ls-remote' genuinely tests the stored credential.
# Prompts are disabled so a missing/expired credential fails fast instead of blocking.
if ($g) {
    $probe = "https://github.com/4m9ccm98gt-rgb/development-management.git"
    $oldTP = $env:GIT_TERMINAL_PROMPT; $oldGCM = $env:GCM_INTERACTIVE
    $env:GIT_TERMINAL_PROMPT = "0"; $env:GCM_INTERACTIVE = "never"
    $ls = (& git ls-remote --heads $probe 2>&1) -join "`n"
    $lsExit = $LASTEXITCODE
    $env:GIT_TERMINAL_PROMPT = $oldTP; $env:GCM_INTERACTIVE = $oldGCM
    if ($lsExit -eq 0) {
        OKV "git remote auth: OK (git can authenticate to a private repo)"
    } elseif ($ls -match "Authentication failed|could not read Username|terminal prompts disabled|invalid credentials|403|401") {
        ACTION "git push/pull auth failed (Git Credential Manager credential missing/expired). Fix: docs\operator_runbook.md section 6 (GitHub re-auth). Local git still works; push/pull to GitHub will not."
    } else {
        INFO ("git remote auth probe inconclusive (offline?): " + (($ls -split "`n") | Select-Object -First 1))
    }
}
L ""

# ---------- canonical repos ----------
L ("## Repos (" + $Repos + ")")
L ("{0,-34} {1,-30} {2,-14} {3,-16} {4,-8} {5}" -f "repo","branch","sync","uncommitted","venv","run/build/deploy")
foreach ($r in $Canon) {
    $p = Join-Path $Repos $r.name
    if (-not (Test-Path -LiteralPath (Join-Path $p ".git"))) { ERRV ($r.name + ": NOT found at " + $p); continue }
    $isArchived = $Archived -contains $r.name
    Push-Location $p
    try {
        if (-not $NoFetch) { & git fetch --quiet 2>$null }
        $br = (& git rev-parse --abbrev-ref HEAD 2>$null)

        # branch classification
        $branchNote = ""
        if ($br -eq $r.branch) { }
        elseif ($ActiveBranch[$r.name] -and $br -eq $ActiveBranch[$r.name]) { $branchNote = "active-wip" }
        elseif ($isArchived) { $branchNote = "archived" }
        else { $branchNote = "unexpected" }

        # uncommitted: split tracked-modified vs untracked-only
        $porc = @(& git status --porcelain 2>$null)
        $modTracked = @($porc | Where-Object { $_ -notmatch '^\?\?' }).Count
        $untracked  = @($porc | Where-Object { $_ -match '^\?\?' }).Count
        $uncommitted = if ($modTracked -gt 0) { ("mod " + $modTracked + " / untrk " + $untracked) } elseif ($untracked -gt 0) { ("untrk " + $untracked) } else { "0" }

        # sync vs own upstream
        $ab = (& git rev-list --left-right --count "@{u}...HEAD" 2>$null)
        $behind = 0; $ahead = 0; $sync = "no-upstream"
        if ($ab -match "^(\d+)\s+(\d+)$") {
            $behind = [int]$Matches[1]; $ahead = [int]$Matches[2]
            $sync = if ($behind -eq 0 -and $ahead -eq 0) { "up-to-date" } else { ("behind " + $behind + " / ahead " + $ahead) }
        }

        $venvPy = Join-Path $p ".venv\Scripts\python.exe"
        $venv = if (Test-Path -LiteralPath $venvPy) { ((& $venvPy --version 2>&1) -replace "Python ","") } else { "-" }
        $names = @(Get-ChildItem -LiteralPath $p -File | ForEach-Object { $_.Name.ToLower() })
        $run = if ($names -match "run_dev") { "Y" } else { "-" }
        $bld = if ($names -match "build.*\.(cmd|bat)$") { "Y" } else { "-" }
        $dep = if (($names -match "update.*\.(cmd|ps1)$") -or ($names -match "^deploy")) { "Y" } else { "-" }

        $brShow = if ($branchNote) { $br + " (" + $branchNote + ")" } else { $br }
        L ("{0,-34} {1,-30} {2,-14} {3,-16} {4,-8} {5}" -f $r.name, $brShow, $sync, $uncommitted, $venv, ($run + "/" + $bld + "/" + $dep))

        switch ($branchNote) {
            "unexpected" { ACTION ($r.name + ": on '" + $br + "', expected default '" + $r.branch + "'. git switch " + $r.branch + " (or note it as intentional).") }
            "active-wip" { INTENT ($r.name + ": on active work branch '" + $br + "' (expected).") }
            "archived"   { INFO   ($r.name + ": archived repo, on '" + $br + "'.") }
        }
        if ($behind -gt 0) {
            if ($isArchived) { INFO ($r.name + ": " + $sync + " (archived).") }
            else { ACTION ($r.name + ": " + $sync + " vs its upstream - git pull.") }
        }
        if ($modTracked -gt 0) { ACTION ($r.name + ": " + $modTracked + " modified tracked file(s) uncommitted - review before it is lost.") }
        elseif ($untracked -gt 0) { INFO ($r.name + ": " + $untracked + " untracked file(s) (often build output). Check they belong in .gitignore.") }
        if ($venv -eq "-") { INFO ($r.name + ": no .venv (RUN_DEV.cmd creates it on first run).") }
    } finally { Pop-Location }
}
L ""

# ---------- backups ----------
L "## Backups (Git-excluded data)"
$bkRoot = Join-Path $env:USERPROFILE "DevDataBackups"
if (Test-Path -LiteralPath $bkRoot) {
    $last = Get-ChildItem -LiteralPath $bkRoot -Directory -Filter "devdata-*" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    if ($last) {
        $ageDays = [int]((Get-Date) - $last.CreationTime).TotalDays
        if ($ageDays -le 8) { OKV ("last dev-data backup: " + $last.Name + "  (" + $ageDays + " day(s) ago)") }
        else { ACTION ("last dev-data backup is " + $ageDays + " day(s) old - run BACKUP_DEV_DATA_CLICK_ME.cmd") }
    } else { ACTION "DevDataBackups exists but no devdata-* backup yet - run BACKUP_DEV_DATA_CLICK_ME.cmd" }
} else { ACTION "no dev-data backup found. Run development-management\scripts\BACKUP_DEV_DATA_CLICK_ME.cmd" }
if (Test-Path -LiteralPath "E:\") {
    $free = try { [int]((Get-PSDrive E).Free / 1GB) } catch { -1 }
    OKV ("E: backup drive present  (~" + $free + " GB free)")
} else { INFO "E: backup drive not connected - the second copy is skipped until you plug it in." }
L ""

# ---------- disk ----------
L "## Disk"
try {
    $freeGB = [int]((Get-PSDrive C).Free / 1GB)
    if ($freeGB -ge 20) { OKV ("C: free space ~" + $freeGB + " GB") } else { ACTION ("C: free space low: ~" + $freeGB + " GB") }
} catch { ACTION "could not read C: free space" }
L ""

# ---------- other git repos under Documents (informational) ----------
L "## Other git repos under Documents  (see docs/pc_repo_audit.md; do NOT delete without review)"
$found = Get-ChildItem "C:\Users\suisy\Documents" -Directory -Recurse -Depth 3 -Force -ErrorAction SilentlyContinue |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ".git") } |
    Where-Object { $_.FullName -notlike ($Repos + "*") }
foreach ($d in $found) {
    Push-Location $d.FullName
    $pc = @(& git status --porcelain 2>$null)
    $mt = @($pc | Where-Object { $_ -notmatch '^\?\?' }).Count
    $rem = (& git remote get-url origin 2>$null)
    Pop-Location
    $tag = if ($mt -gt 0) { "REVIEW - " + $mt + " modified tracked (see pc_repo_audit.md)" } else { "clean/expected" }
    INFO ($d.FullName.Replace("C:\Users\suisy\Documents\","") + "  [" + $tag + "]" + $(if ($rem) { "  <- " + $rem } else { "" }))
}
L ""

# ---------- summary ----------
L "## Summary"
L ("ERROR: " + $script:err + "   ACTION: " + $script:action + "   INTENTIONAL: " + $script:intent + "   INFO: " + $script:info)
if ($script:err -gt 0)      { L "=> Fix the [ERROR] lines first (missing tool / repo / auth)." }
elseif ($script:action -gt 0){ L "=> Review each [ACTION] line. [INTENTIONAL] / [INFO] are expected - ignore unless they surprise you." }
else                        { L "=> No ERROR / ACTION. All clear." }
L "Paste this whole report to ChatGPT if any line is unclear."

$lines | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host ""
Write-Host ("report saved: " + $ReportPath)
