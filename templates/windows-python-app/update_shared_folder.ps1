<#
Safely update a distribution target (shared folder / external HDD).
Modeled on beverage-inventory-ordering-system/python_app/update_shared_folder.ps1.

Guarantees:
  - Payload (EXE, _internal runtime) is separated from business data.
  - No robocopy /MIR over the whole target; only the runtime dir is mirrored.
  - Every file under the business-data dir is SHA-256 hashed and counted before
    the update, and re-checked afterwards; any change or loss aborts with an error.
  - The EXE is replaced atomically (copy to temp, then Move).
  - The target path is never guessed or stored; it is pasted at run time.
  - Windows PowerShell 5.1 compatible. Keep this file ASCII-only.

Replace <...> with real values for this app.
#>
param(
    [string]$TargetPath = "",
    [string]$SourcePath = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- app-specific values ---
$AppExeName   = "<AppName>.exe"
$BuildDirName = "dist\<AppName>"      # build output folder
$RuntimeDir   = "_internal"            # runtime dir that may be fully mirrored
$DataDirName  = "data"                 # business-data dir (never updated, verified)
# ---------------------------

$Source = if ($SourcePath) { [System.IO.Path]::GetFullPath($SourcePath) } else { Join-Path $ScriptRoot $BuildDirName }
$Log    = if ($LogPath)    { [System.IO.Path]::GetFullPath($LogPath) }    else { Join-Path $ScriptRoot "update_shared_folder_result.txt" }

function Write-UpdateLog([string]$Text) {
    Write-Host $Text
    Add-Content -LiteralPath $Log -Value $Text -Encoding UTF8
}

function Get-DataHashes([string]$DataPath) {
    $hashes = @{}
    if (-not (Test-Path -LiteralPath $DataPath -PathType Container)) { return $hashes }
    foreach ($file in Get-ChildItem -LiteralPath $DataPath -File -Recurse -Force) {
        $relative = $file.FullName.Substring($DataPath.Length).TrimStart("\")
        $hashes[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
    return $hashes
}

function Assert-DataUnchanged([string]$DataPath, [hashtable]$Before) {
    foreach ($relative in $Before.Keys) {
        $path = Join-Path $DataPath $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Business data disappeared: $DataDirName\$relative" }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $Before[$relative]) {
            throw "Business data changed during update: $DataDirName\$relative"
        }
    }
    $after = if (Test-Path -LiteralPath $DataPath) { @(Get-ChildItem -LiteralPath $DataPath -File -Recurse -Force) } else { @() }
    if ($after.Count -ne $Before.Count) { throw "Business data file count changed during update." }
}

try {
    Set-Content -LiteralPath $Log -Value "<app-name> shared-folder update" -Encoding UTF8
    Write-UpdateLog ("date:   " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    Write-UpdateLog ("source: " + $Source)

    $sourceExe     = Join-Path $Source $AppExeName
    $sourceRuntime = Join-Path $Source $RuntimeDir
    if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf))          { throw "Source EXE not found. Run BUILD_EXE_CLICK_ME.cmd first. No target was changed." }
    if (-not (Test-Path -LiteralPath $sourceRuntime -PathType Container)) { throw "Source $RuntimeDir not found. No target was changed." }

    if (-not $TargetPath) {
        Add-Type -AssemblyName Microsoft.VisualBasic
        $TargetPath = [Microsoft.VisualBasic.Interaction]::InputBox(
            "Paste the exact distribution folder path. This script does not guess or store it.",
            "Distribution folder", "")
        $TargetPath = ($TargetPath -as [string]).Trim().Trim('"')
        if (-not $TargetPath) { throw "Canceled. No target was changed." }
    }

    $Target = [System.IO.Path]::GetFullPath($TargetPath)
    if (-not (Test-Path -LiteralPath $Target -PathType Container)) { throw "Target folder not found: $Target" }
    if ([StringComparer]::OrdinalIgnoreCase.Equals($Source.TrimEnd('\'), $Target.TrimEnd('\'))) { throw "Source and target must be different folders." }

    $targetData = Join-Path $Target $DataDirName
    $dataHashes = Get-DataHashes $targetData
    Write-UpdateLog ("target: " + $Target)
    Write-UpdateLog ("protected data files before update: " + $dataHashes.Count)

    $targetRuntime = Join-Path $Target $RuntimeDir
    if (-not (Test-Path -LiteralPath $targetRuntime)) { New-Item -ItemType Directory -Path $targetRuntime | Out-Null }
    Write-UpdateLog "Synchronize runtime: $RuntimeDir"
    & robocopy $sourceRuntime $targetRuntime /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "$RuntimeDir sync failed (robocopy exit $LASTEXITCODE)" }

    Write-UpdateLog "Update $AppExeName"
    $targetExe = Join-Path $Target $AppExeName
    $tempExe   = Join-Path $Target (".{0}.update" -f $AppExeName)
    Copy-Item -LiteralPath $sourceExe -Destination $tempExe -Force
    Move-Item -LiteralPath $tempExe -Destination $targetExe -Force

    Assert-DataUnchanged $targetData $dataHashes
    Write-UpdateLog ("business data SHA-256 verified: " + $dataHashes.Count + " files")
    Write-UpdateLog ("target EXE SHA-256: " + (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash)
    Write-UpdateLog "DONE"
    exit 0
} catch {
    Write-Host ("[ERROR] " + $_.Exception.Message) -ForegroundColor Red
    try { Add-Content -LiteralPath $Log -Value ("ERROR: " + $_.Exception.Message) -Encoding UTF8 } catch {}
    exit 1
}
