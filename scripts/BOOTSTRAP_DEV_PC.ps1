<#
BOOTSTRAP_DEV_PC.ps1 - rebuild this development environment on a fresh Windows PC.

What it DOES (idempotent, fail-safe, re-runnable):
  1. Check git / python (py) / gh are installed. Offer winget install lines (or -InstallMissing).
  2. Check GitHub auth (gh token AND git push/pull credential). Stop with a pointer if not ready.
  3. Create the canonical repos root (default C:\Users\suisy\Documents\Development\repos).
  4. Clone development-management first, then read scripts\repo_types.toml for the rest.
  5. Clone each canonical repo that is missing. Each repo keeps its OWN GitHub default branch
     (detected live via 'git ls-remote --symref origin HEAD' - so food-cost is correct whether
     it is codex/bootstrap-invoice-reading or main).
  6. Report which repos expect a RUN_DEV entrypoint and whether .venv exists yet.
  7. Point at DEV_DOCTOR and check_standards for verification.

What it does NOT do (on purpose):
  - It never overwrites, resets, or deletes an existing repo or working tree. Existing repos
    are only fetched (never merged/reset) unless -NoFetch.
  - It never restores Git-external data (databases / credentials / real settings / shared
    folders / HDD). Those are recovered manually via docs\backup_restore.md.
  - It does not build EXEs, start servers, or launch any GUI.
  - It does not create venvs by default (RUN_DEV.cmd does that on first run). -PrepareVenvs
    creates a bare .venv + installs requirements.txt for repos that have one (no app launch).

Verify without a fresh PC:
  BOOTSTRAP_DEV_PC.ps1 -ReposRoot <temp dir> -Only development-management,hospitality-review-reply -WhatIf
  then drop -WhatIf to actually clone into the temp dir, then run again to see idempotency.

Windows PowerShell 5.1 compatible. ASCII only.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ReposRoot   = "C:\Users\suisy\Documents\Development\repos",
    [string]$GitHubOwner = "4m9ccm98gt-rgb",
    [string[]]$Only      = @(),          # limit to these repo names (for testing)
    [switch]$InstallMissing,             # run winget for any missing tool
    [switch]$PrepareVenvs,               # create .venv + pip install -r requirements.txt (no app launch)
    [switch]$NoFetch                     # do not 'git fetch' existing repos
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

# 'powershell -File ... -Only a,b' does not always split on commas; normalize.
$Only = @($Only | ForEach-Object { $_ -split '[,\s]+' } | Where-Object { $_ })

$script:warn = 0; $script:err = 0
function Say($m)  { Write-Host $m }
function Ok($m)   { Write-Host ("[OK]    " + $m) }
function Warn($m) { $script:warn++; Write-Host ("[WARN]  " + $m) -ForegroundColor Yellow }
function Err($m)  { $script:err++;  Write-Host ("[ERROR] " + $m) -ForegroundColor Red }
function Step($m) { Write-Host ""; Write-Host ("=== " + $m + " ===") }

# Run git without letting its stderr become a terminating PowerShell error.
function Invoke-Git {
    $ga = $args
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $text = (& git @ga 2>&1 | ForEach-Object { $_.ToString() }) -join "`n"
        return [pscustomobject]@{ Code = $LASTEXITCODE; Text = $text.Trim() }
    } finally { $ErrorActionPreference = $old }
}

# Fallback list used only if repo_types.toml cannot be read yet. development-management is
# always included (it is the management repo and is not listed in repo_types.toml).
$FallbackRepos = @(
    "development-management","beverage-inventory-ordering-system","call-reception-assistant",
    "food-cost-calculation-system","inventory-reconciliation-system","menu-sheet-generator",
    "next-day-setup","qr-supply-ordering-system","kitchen-calendar","hospitality-review-reply"
)

# repo type -> is a RUN_DEV.cmd entrypoint expected?
$RunDevExpected = @{ "desktop" = $true; "web" = $true; "service" = $true; "lib" = $false; "knowledge" = $false; "archived" = $false }
# beverage keeps its RUN_DEV under python_app\
$RunDevSubdir = @{ "beverage-inventory-ordering-system" = "python_app" }
# menu-sheet-generator is .NET: no RUN_DEV even though type is desktop
$NoRunDev = @("menu-sheet-generator","call-reception-assistant")

# ---------------------------------------------------------------- 1. toolchain
Step "1. Toolchain (git / python / gh)"

function Have($exe) { $null -ne (Get-Command $exe -ErrorAction SilentlyContinue) }
$wingetIds = @{ "git" = "Git.Git"; "python" = "Python.Python.3.12"; "gh" = "GitHub.CLI" }
$missing = @()
foreach ($t in @("git","python","gh")) {
    $probe = if ($t -eq "python") { (Have "py") -or (Have "python") } else { Have $t }
    if ($probe) {
        $v = switch ($t) {
            "git"    { (& git --version) }
            "python" { if (Have "py") { (& py --version) } else { (& python --version) } }
            "gh"     { ((& gh --version) | Select-Object -First 1) }
        }
        Ok ($t + ": " + ($v -join " ").Trim())
    } else {
        $missing += $t
        Warn ($t + " not found. winget install --id " + $wingetIds[$t] + " -e")
    }
}
if ($missing.Count -gt 0) {
    if ($InstallMissing -and (Have "winget")) {
        foreach ($t in $missing) {
            if ($PSCmdlet.ShouldProcess($wingetIds[$t], "winget install")) {
                & winget install --id $wingetIds[$t] -e --accept-source-agreements --accept-package-agreements
            }
        }
        Warn "Re-open PowerShell so PATH refreshes, then run this script again."
        return
    }
    Err "Install the missing tool(s) above (or re-run with -InstallMissing), then re-run. Stopping."
    return
}

# ---------------------------------------------------------------- 2. GitHub auth
Step "2. GitHub authentication (gh token + git push/pull credential)"

$ghAuth = (& gh auth status 2>&1) -join "`n"
$ghExit = $LASTEXITCODE
$ghBroken = ($ghAuth -match "(?m)^\s*X .*(Failed to log in|token .* is invalid|expired|revoked)")
if ($ghExit -eq 0 -and -not $ghBroken) {
    $scopes = ""; if ($ghAuth -match "Token scopes:\s*(.+)") { $scopes = $Matches[1].Trim() }
    Ok ("gh auth: logged in. scopes: " + $scopes)
    if ($scopes -and ($scopes -notmatch "workflow")) { Warn "gh token missing 'workflow' scope. Run: gh auth refresh -s workflow" }
} else {
    Err "gh is not authenticated. Do docs\operator_runbook.md section 6-1 (gh auth login), then re-run. Stopping."
    return
}

$probeUrl = "https://github.com/$GitHubOwner/development-management.git"
$oldTP = $env:GIT_TERMINAL_PROMPT; $oldGCM = $env:GCM_INTERACTIVE
$env:GIT_TERMINAL_PROMPT = "0"; $env:GCM_INTERACTIVE = "never"
$lsExit = (Invoke-Git ls-remote --heads $probeUrl).Code
$env:GIT_TERMINAL_PROMPT = $oldTP; $env:GCM_INTERACTIVE = $oldGCM
if ($lsExit -eq 0) {
    Ok "git push/pull auth: OK (git can reach a private repo)"
} else {
    Warn "git could not authenticate to a private repo non-interactively. On the first 'git clone' below,"
    Warn "Git Credential Manager should open a browser - sign in and Authorize. If not, see operator_runbook.md 6-2."
}

# ---------------------------------------------------------------- 3. repos root
Step "3. Canonical repos root"

if (Test-Path -LiteralPath $ReposRoot) {
    Ok ("exists: " + $ReposRoot)
} elseif ($PSCmdlet.ShouldProcess($ReposRoot, "create directory")) {
    New-Item -ItemType Directory -Path $ReposRoot -Force | Out-Null
    Ok ("created: " + $ReposRoot)
}

# ---------------------------------------------------------------- helpers
function Get-DefaultBranch([string]$Url) {
    $r = Invoke-Git ls-remote --symref $Url HEAD
    if ($r.Code -eq 0 -and $r.Text -match '(?m)^ref:\s+refs/heads/(\S+)\s+HEAD') { return $Matches[1] }
    return $null
}

function Ensure-Repo([string]$Name) {
    $url  = "https://github.com/$GitHubOwner/$Name.git"
    $dest = Join-Path $ReposRoot $Name
    if (Test-Path -LiteralPath (Join-Path $dest ".git")) {
        $cur = (Invoke-Git -C $dest rev-parse --abbrev-ref HEAD).Text
        if ($NoFetch) {
            Ok ($Name + ": exists (branch " + $cur + ") - left untouched")
        } else {
            [void](Invoke-Git -C $dest fetch --quiet --prune origin)
            $def = ((Invoke-Git -C $dest symbolic-ref --quiet refs/remotes/origin/HEAD).Text) -replace '^refs/remotes/origin/',''
            $sync = ""
            if ($def) {
                $ab = (Invoke-Git -C $dest rev-list --left-right --count "HEAD...origin/$def").Text
                if ($ab -match '^\s*(\d+)\s+(\d+)') { $sync = " (ahead " + $Matches[1] + " / behind " + $Matches[2] + " vs origin/" + $def + ")" }
            }
            Ok ($Name + ": exists (branch " + $cur + ")" + $sync + " - fetched only, not merged")
        }
        return
    }
    if (Test-Path -LiteralPath $dest) { Err ($Name + ": " + $dest + " exists but is not a git repo. Skipping (move it aside first)."); return }
    $def = Get-DefaultBranch $url
    $cloneMsg = "git clone " + $url
    if ($def) { $cloneMsg = $cloneMsg + " (default branch: " + $def + ")" }
    if (-not $PSCmdlet.ShouldProcess($dest, $cloneMsg)) { return }
    $c = Invoke-Git clone --quiet $url $dest
    if ($c.Code -ne 0) { Err ($Name + ": clone failed (exit " + $c.Code + ") - " + $c.Text); return }
    [void](Invoke-Git -C $dest remote set-head origin -a)
    $cur = (Invoke-Git -C $dest rev-parse --abbrev-ref HEAD).Text
    Ok ($Name + ": cloned. default branch = " + $cur)
}

# ---------------------------------------------------------------- 4. clone development-management, load repo list
Step "4. development-management + canonical repo list"

Ensure-Repo "development-management"

$repoTypes = @{}
$typesFile = Join-Path $ReposRoot "development-management\scripts\repo_types.toml"
if (Test-Path -LiteralPath $typesFile) {
    $inTypes = $false
    foreach ($ln in Get-Content -LiteralPath $typesFile) {
        if ($ln -match '^\s*\[types\]\s*$') { $inTypes = $true; continue }
        if ($inTypes -and $ln -match '^\s*\[') { break }
        if ($inTypes -and $ln -match '^\s*([A-Za-z0-9._-]+)\s*=\s*"([a-z]+)"') { $repoTypes[$Matches[1]] = $Matches[2] }
    }
}
if ($repoTypes.Count -gt 0) {
    Ok ("repo_types.toml: " + $repoTypes.Count + " managed repos")
    $repoList = @("development-management") + ($repoTypes.Keys | Sort-Object)
} else {
    Warn "Could not read repo_types.toml yet - using the built-in fallback list."
    $repoList = $FallbackRepos
}
if ($Only.Count -gt 0) { $repoList = $repoList | Where-Object { $Only -contains $_ } }

# ---------------------------------------------------------------- 5. clone the rest
Step "5. Clone canonical repos (existing repos are only fetched, never reset)"

foreach ($name in ($repoList | Where-Object { $_ -ne "development-management" })) { Ensure-Repo $name }

# ---------------------------------------------------------------- 6. RUN_DEV / venv report
Step "6. RUN_DEV entrypoints and venvs"

foreach ($name in $repoList) {
    $dest = Join-Path $ReposRoot $name
    if (-not (Test-Path -LiteralPath $dest)) { continue }
    if ($name -eq "development-management") { Ok ($name + ": management repo (no RUN_DEV; has scripts\ and templates\)"); continue }
    $type = $repoTypes[$name]
    $sub  = $RunDevSubdir[$name]
    $runDevDir = if ($sub) { Join-Path $dest $sub } else { $dest }
    $runDev = Join-Path $runDevDir "RUN_DEV.cmd"
    $venv   = Join-Path $runDevDir ".venv\Scripts\python.exe"
    if ($NoRunDev -contains $name) {
        $typeStr = if ($type) { $type } else { "?" }
        Ok ($name + ": no RUN_DEV expected (" + $typeStr + " / .NET / not implemented)")
        continue
    }
    if ($RunDevExpected[$type]) {
        if (Test-Path -LiteralPath $runDev) {
            $venvMsg = if (Test-Path -LiteralPath $venv) { ".venv ready" } else { ".venv not created yet (RUN_DEV.cmd makes it on first run)" }
            Ok ($name + ": " + ($runDev.Substring($dest.Length).TrimStart('\')) + " present - " + $venvMsg)
            if ($PrepareVenvs -and -not (Test-Path -LiteralPath $venv)) {
                $req = Join-Path $runDevDir "requirements.txt"
                if ((Test-Path -LiteralPath $req) -and $PSCmdlet.ShouldProcess($runDevDir, "create .venv + pip install -r requirements.txt")) {
                    try {
                        & py -3 -m venv (Join-Path $runDevDir ".venv")
                        & (Join-Path $runDevDir ".venv\Scripts\python.exe") -m pip install --quiet --upgrade pip
                        & (Join-Path $runDevDir ".venv\Scripts\python.exe") -m pip install --quiet -r $req
                        Ok ($name + ": .venv prepared")
                    } catch { Warn ($name + ": venv prepare failed - " + $_.Exception.Message + " (RUN_DEV.cmd will retry on first run)") }
                }
            }
        } else {
            Warn ($name + ": expected RUN_DEV.cmd not found at " + $runDevDir)
        }
    } else {
        Ok ($name + ": type '" + $type + "' - no RUN_DEV entrypoint expected")
    }
}

# ---------------------------------------------------------------- 7. Git-external data + verification
Step "7. Next steps (NOT done by this script)"

Say "Git-external data (databases / credentials / real settings / shared folders / HDD) is NOT"
Say "restored by this script. Recover it deliberately using:"
Say ("    " + (Join-Path $ReposRoot "development-management\docs\backup_restore.md"))
Say ""
Say "Then verify the environment:"
Say ("    " + (Join-Path $ReposRoot "development-management\scripts\DEV_DOCTOR_CLICK_ME.cmd"))
Say "    (expects each repo on its GitHub default branch; food-cost's default is whatever GitHub"
Say "     says right now - see docs\food_cost_default_branch.md)"
Say ""
Say "CI runs automatically on GitHub (warning-only). Nothing to set up locally."

Step "Summary"
Write-Host ("WARN: " + $script:warn + "   ERROR: " + $script:err)
if ($script:err -gt 0)      { Write-Host "=> Fix the [ERROR] lines and re-run. Safe to re-run (idempotent)." }
elseif ($script:warn -gt 0) { Write-Host "=> Review [WARN] lines. Re-run any time; existing repos are never reset." }
else                        { Write-Host "=> Bootstrap complete. Run DEV_DOCTOR next." }
