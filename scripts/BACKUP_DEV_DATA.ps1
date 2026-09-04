<#
Back up all Git-excluded development data (DBs, real settings, credentials,
local-only files, business data) into one dated folder. Read-only on every
source. Never writes to the live data locations.

The output contains real values -> do NOT put the output under Git.
Keep a copy on a separate drive (external / OneDrive) via -SecondDest.

Usage:
  powershell -ExecutionPolicy Bypass -File BACKUP_DEV_DATA.ps1
  powershell -ExecutionPolicy Bypass -File BACKUP_DEV_DATA.ps1 -Dest D:\DevDataBackups -SecondDest "$HOME\OneDrive\DevDataBackups"
  powershell -ExecutionPolicy Bypass -File BACKUP_DEV_DATA.ps1 -SkipLargeBusinessData

Windows PowerShell 5.1 compatible. ASCII only.
#>
param(
    [string]$Dest = (Join-Path $env:USERPROFILE "DevDataBackups"),
    [string]$SecondDest = "",
    [switch]$SkipLargeBusinessData
)

$ErrorActionPreference = "Stop"
$Repos = "C:\Users\suisy\Documents\Development\repos"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Root  = Join-Path $Dest ("devdata-" + $Stamp)
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$Manifest = Join-Path $Root "MANIFEST.txt"
$Restore  = Join-Path $Root "RESTORE.txt"
Set-Content -LiteralPath $Manifest -Value ("backup created: " + $Stamp) -Encoding UTF8
Set-Content -LiteralPath $Restore  -Value "# Where each item restores to. Move the current file aside first." -Encoding UTF8

$pyExe = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

function Add-Manifest([string]$rel, [string]$full) {
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $h = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
        $s = (Get-Item -LiteralPath $full).Length
        Add-Content -LiteralPath $Manifest -Value ($s.ToString().PadLeft(12) + "  " + $h + "  " + $rel) -Encoding UTF8
    }
}

function Copy-Plain([string]$src, [string]$relDest, [string]$restoreNote) {
    if (-not (Test-Path -LiteralPath $src)) { Write-Host ("[skip] not found: " + $src); return }
    $dst = Join-Path $Root $relDest
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    if ((Get-Item -LiteralPath $src).PSIsContainer) {
        & robocopy $src $dst /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
        Get-ChildItem -LiteralPath $dst -File -Recurse | ForEach-Object {
            Add-Manifest ($_.FullName.Substring($Root.Length).TrimStart("\")) $_.FullName
        }
    } else {
        Copy-Item -LiteralPath $src -Destination $dst -Force
        Add-Manifest $relDest $dst
    }
    Add-Content -LiteralPath $Restore -Value ($relDest + "  ->  " + $restoreNote) -Encoding UTF8
    Write-Host ("[ok] " + $relDest)
}

function Copy-Sqlite([string]$src, [string]$relDest, [string]$restoreNote) {
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { Write-Host ("[skip] not found: " + $src); return }
    $dst = Join-Path $Root $relDest
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    # SQLite online backup API: safe even while the app is running.
    & $pyExe -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "$src" "$dst"
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("[WARN] sqlite backup failed, plain copy: " + $src)
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    $chk = & $pyExe -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('PRAGMA integrity_check').fetchone()[0])" "$dst"
    Add-Content -LiteralPath $Manifest -Value ("  integrity_check(" + $relDest + "): " + $chk) -Encoding UTF8
    Add-Manifest $relDest $dst
    Add-Content -LiteralPath $Restore -Value ($relDest + "  ->  " + $restoreNote) -Encoding UTF8
    Write-Host ("[ok] " + $relDest + "  (integrity: " + $chk + ")")
}

$LA = $env:LOCALAPPDATA

# --- food-cost (Oreden) ---
Copy-Sqlite "$LA\FoodCostCalculation\food_cost.db" "food-cost\food_cost.db" "%LOCALAPPDATA%\FoodCostCalculation\food_cost.db"
Copy-Plain  "$LA\FoodCostCalculation\config" "food-cost\config" "%LOCALAPPDATA%\FoodCostCalculation\config\  (google_capture.json holds bridge_secret; keep out of Git)"
if (-not $SkipLargeBusinessData) {
    foreach ($d in "collected_originals","crops","google_inbox","uploads") {
        Copy-Plain "$LA\FoodCostCalculation\$d" "food-cost\$d" "%LOCALAPPDATA%\FoodCostCalculation\$d\  (invoice images / business data)"
    }
}

# --- inventory-reconciliation ---
Copy-Plain "$LA\SalesInventoryCheckTool\credentials.json" "inventory-reconciliation\credentials.json" "%LOCALAPPDATA%\SalesInventoryCheckTool\credentials.json  (temairazu / agent credentials; keep out of Git)"
Copy-Plain "$LA\SalesInventoryCheckTool\print_config" "inventory-reconciliation\print_config" "%LOCALAPPDATA%\SalesInventoryCheckTool\print_config\"
Copy-Plain "$Repos\inventory-reconciliation-system\config\chrome_profile.txt" "inventory-reconciliation\config\chrome_profile.txt" "<repo>\inventory-reconciliation-system\config\chrome_profile.txt"
Copy-Plain "$Repos\inventory-reconciliation-system\config\print_preparation.json" "inventory-reconciliation\config\print_preparation.json" "<repo>\inventory-reconciliation-system\config\print_preparation.json"

# --- next-day-setup ---
Copy-Plain  "$Repos\next-day-setup\dinner_system\master_settings.json" "next-day-setup\master_settings.json" "<repo>\next-day-setup\dinner_system\master_settings.json"
Copy-Plain  "$Repos\next-day-setup\dinner_system\ui_prefs.json" "next-day-setup\ui_prefs.json" "<repo>\next-day-setup\dinner_system\ui_prefs.json"
Copy-Plain  "$Repos\next-day-setup\dinner_system\config\print_preparation.json" "next-day-setup\config_print_preparation.json" "<repo>\next-day-setup\dinner_system\config\print_preparation.json"
Copy-Plain  "$Repos\next-day-setup\shared_folder_path.txt" "next-day-setup\shared_folder_path.txt" "<repo>\next-day-setup\shared_folder_path.txt  (shared distribution target path)"

# The daily-work data dir has a Japanese name; locate it via the DB file inside it.
$dbHit = Get-ChildItem "$Repos\next-day-setup\dinner_system" -Recurse -Filter "kitchen_data.sqlite3" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($dbHit) {
    $hozon = $dbHit.DirectoryName
    Copy-Sqlite (Join-Path $hozon "kitchen_data.sqlite3") "next-day-setup\workdata\kitchen_data.sqlite3" ("<repo>\next-day-setup\dinner_system\" + (Split-Path -Leaf $hozon) + "\kitchen_data.sqlite3")
    $dst = Join-Path $Root "next-day-setup\workdata"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    & robocopy $hozon $dst /E /XF "*.sqlite3" "*.sqlite3-*" /COPY:DAT /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    Get-ChildItem -LiteralPath $dst -File -Recurse | ForEach-Object { Add-Manifest ($_.FullName.Substring($Root.Length).TrimStart("\")) $_.FullName }
    Add-Content -LiteralPath $Restore -Value ("next-day-setup\workdata\  ->  <repo>\next-day-setup\dinner_system\" + (Split-Path -Leaf $hozon) + "\") -Encoding UTF8
    Write-Host "[ok] next-day-setup\workdata (JSON / JSONL / subdirs)"
} else {
    Write-Host "[skip] next-day-setup work-data dir not found"
}

# --- qr-supply ---
Copy-Sqlite "$Repos\qr-supply-ordering-system\database\qr_supply.sqlite3" "qr-supply\qr_supply.sqlite3" "<repo>\qr-supply-ordering-system\database\qr_supply.sqlite3"

# --- food-cost repo-local config ---
Copy-Plain "$Repos\food-cost-calculation-system\google_capture.json" "food-cost\repo_google_capture.json" "<repo>\food-cost-calculation-system\google_capture.json  (holds bridge_secret; keep out of Git)"

Add-Content -LiteralPath $Restore -Value "" -Encoding UTF8
Add-Content -LiteralPath $Restore -Value "# gh auth: do not export the token. On a new machine run: gh auth login  (scopes: repo, workflow, read:org, gist)" -Encoding UTF8

Write-Host ""
Write-Host ("primary backup: " + $Root)

if ($SecondDest -ne "") {
    $Root2 = Join-Path $SecondDest ("devdata-" + $Stamp)
    New-Item -ItemType Directory -Force -Path $Root2 | Out-Null
    & robocopy $Root $Root2 /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    Write-Host ("second copy   : " + $Root2)
}

Write-Host ""
Write-Host ("MANIFEST: " + $Manifest)
Write-Host ("RESTORE : " + $Restore)
Write-Host "Keep this output OUT of Git. Also store it on a separate / offline drive."
