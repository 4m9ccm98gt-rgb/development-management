<#
DEV DOCTOR - local development environment health check (Windows real machine).

Counterpart to development-management/scripts/check_standards.py:
  check_standards.py = GitHub side (does the repo meet the standard?)
  DEV_DOCTOR         = this machine side (are the tools / clones / venvs / backups OK?)

Double-click DEV_DOCTOR_CLICK_ME.cmd. Read the Summary. Paste the whole report
into ChatGPT etc. to get a diagnosis. It changes nothing (read-only).

Windows PowerShell 5.1 compatible. ASCII only (folder names with non-ASCII are
discovered at run time, never written in this file).
#>
param(
    [switch]$NoFetch,
    [string]$ReportPath = (Join-Path $env:USERPROFILE "DEV_DOCTOR_report.txt")
)

$ErrorActionPreference = "Continue"
$Repos = "C:\Users\suisy\Documents\Development\repos"
$Canon = @(
    @{ name = "development-management";              branch = "main" },
    @{ name = "next-day-setup";                      branch = "main" },
    @{ name = "inventory-reconciliation-system";     branch = "main" },
    @{ name = "beverage-inventory-ordering-system";  branch = "main" },
    @{ name = "qr-supply-ordering-system";           branch = "main" },
    @{ name = "menu-sheet-generator";                branch = "main" },
    @{ name = "call-reception-assistant";            branch = "main" },
    @{ name = "kitchen-calendar";                    branch = "main" },
    @{ name = "food-cost-calculation-system";        branch = "codex/bootstrap-invoice-reading" }
)

$script:ok = 0; $script:warn = 0; $script:err = 0
$lines = New-Object System.Collections.Generic.List[string]
function L([string]$s) { [void]$lines.Add($s); Write-Host $s }
function OK($m)   { $script:ok++;   L ("[OK]    " + $m) }
function WARNV($m){ $script:warn++; L ("[WARN]  " + $m) }
function ERRV($m) { $script:err++;  L ("[ERROR] " + $m) }
function INFO($m) { L ("[INFO]  " + $m) }

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
if ($g) { OK ("git: " + $g) } else { ERRV "git not found in PATH" }

$pv = FirstLine "py" @("-3","--version")
if (-not $pv) { $pv = FirstLine "python" @("--version") }
if ($pv) { OK ("python: " + $pv) } else { ERRV "python / py launcher not found" }

$gh = FirstLine "gh" @("--version")
if ($gh) {
    OK ("gh: " + $gh)
    $auth = (& gh auth status 2>&1) -join "`n"
    if ($auth -match "Logged in") {
        $scopes = ""
        if ($auth -match "Token scopes:\s*(.+)") { $scopes = ($Matches[1].Trim()) }
        OK ("gh auth: logged in. scopes: " + $scopes)
        if ($scopes -and ($scopes -notmatch "workflow")) {
            WARNV "gh token missing 'workflow' scope (needed to push .github/workflows). Re-run: gh auth login"
        }
    } else {
        ERRV "gh not authenticated. Run: gh auth login  (scopes: repo, workflow, read:org, gist)"
    }
} else { WARNV "gh (GitHub CLI) not found. Needed for PR / CI operations." }
L ""

# ---------- canonical repos ----------
L ("## Canonical repos (" + $Repos + ")")
L ("{0,-34} {1,-32} {2,-14} {3,-6} {4,-8} {5}" -f "repo","branch","sync","dirty","venv","run/build/deploy")
foreach ($r in $Canon) {
    $p = Join-Path $Repos $r.name
    if (-not (Test-Path -LiteralPath (Join-Path $p ".git"))) { ERRV ($r.name + ": NOT found at " + $p); continue }
    Push-Location $p
    try {
        if (-not $NoFetch) { & git fetch --quiet 2>$null }
        $br = (& git rev-parse --abbrev-ref HEAD 2>$null)
        $brShow = if ($br -eq $r.branch) { $br } else { $br + " (want " + $r.branch + ")" }
        $dirty = (& git status --porcelain 2>$null | Measure-Object).Count
        $ab = (& git rev-list --left-right --count "@{u}...HEAD" 2>$null)
        $sync = "no-upstream"
        if ($ab -match "^(\d+)\s+(\d+)$") {
            $behind = [int]$Matches[1]; $ahead = [int]$Matches[2]
            if ($behind -eq 0 -and $ahead -eq 0) { $sync = "up-to-date" } else { $sync = ("behind " + $behind + " / ahead " + $ahead) }
        }
        $venvPy = Join-Path $p ".venv\Scripts\python.exe"
        $venv = if (Test-Path -LiteralPath $venvPy) { ((& $venvPy --version 2>&1) -replace "Python ","") } else { "-" }
        $names = @(Get-ChildItem -LiteralPath $p -File | ForEach-Object { $_.Name.ToLower() })
        $run = if ($names -match "run_dev") { "Y" } else { "-" }
        $bld = if ($names -match "build.*\.(cmd|bat)$") { "Y" } else { "-" }
        $dep = if (($names -match "update.*\.(cmd|ps1)$") -or ($names -match "^deploy")) { "Y" } else { "-" }
        L ("{0,-34} {1,-32} {2,-14} {3,-6} {4,-8} {5}" -f $r.name, $brShow, $sync, $dirty, $venv, ($run + "/" + $bld + "/" + $dep))
        if ($br -ne $r.branch) { WARNV ($r.name + ": on '" + $br + "', expected '" + $r.branch + "'") }
        if ($sync -like "behind*") { WARNV ($r.name + ": " + $sync + " - consider git pull") }
        if ($dirty -gt 0) { WARNV ($r.name + ": " + $dirty + " uncommitted change(s) - review before it is lost") }
        if ($venv -eq "-") { WARNV ($r.name + ": no .venv (RUN_DEV.cmd will create it on first run)") }
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
        if ($ageDays -le 8) { OK ("last dev-data backup: " + $last.Name + "  (" + $ageDays + " day(s) ago)") }
        else { WARNV ("last dev-data backup is " + $ageDays + " day(s) old - run BACKUP_DEV_DATA_CLICK_ME.cmd") }
    } else { WARNV "DevDataBackups exists but no devdata-* backup yet - run BACKUP_DEV_DATA_CLICK_ME.cmd" }
} else { WARNV "no dev-data backup found. Run development-management\scripts\BACKUP_DEV_DATA_CLICK_ME.cmd" }
if (Test-Path -LiteralPath "E:\") {
    $free = try { [int]((Get-PSDrive E).Free / 1GB) } catch { -1 }
    OK ("E: backup drive present  (~" + $free + " GB free)")
} else { WARNV "E: backup drive not connected - second-copy is skipped when you run the backup" }
L ""

# ---------- disk ----------
L "## Disk"
try {
    $freeGB = [int]((Get-PSDrive C).Free / 1GB)
    if ($freeGB -ge 20) { OK ("C: free space ~" + $freeGB + " GB") } else { WARNV ("C: free space low: ~" + $freeGB + " GB") }
} catch { WARNV "could not read C: free space" }
L ""

# ---------- stale / extra repos (discovered, informational) ----------
L "## Other git repos under Documents  (see docs/pc_repo_audit.md; do NOT delete without review)"
$found = Get-ChildItem "C:\Users\suisy\Documents" -Directory -Recurse -Depth 3 -Force -ErrorAction SilentlyContinue |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ".git") } |
    Where-Object { $_.FullName -notlike ($Repos + "*") }
foreach ($d in $found) {
    Push-Location $d.FullName
    $dc = (& git status --porcelain 2>$null | Measure-Object).Count
    $rem = (& git remote get-url origin 2>$null)
    Pop-Location
    $tag = if ($dc -gt 0) { "REVIEW - " + $dc + " uncommitted (possible unpushed work)" } else { "clean" }
    INFO ($d.FullName.Replace("C:\Users\suisy\Documents\","") + "  [" + $tag + "]" + $(if ($rem) { "  <- " + $rem } else { "" }))
}
L ""

# ---------- summary ----------
L "## Summary"
L ("OK: " + $script:ok + "   WARN: " + $script:warn + "   ERROR: " + $script:err)
if ($script:err -gt 0) { L "=> ERROR present. Fix the [ERROR] lines first (usually a missing tool or a repo not cloned)." }
elseif ($script:warn -gt 0) { L "=> WARN present. Not blocking, but review each. Paste this whole report to ChatGPT for help." }
else { L "=> All green." }

$lines | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host ""
Write-Host ("report saved: " + $ReportPath)
