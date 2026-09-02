<#
配布先（共有フォルダ / 外付けHDD 等）を安全に更新するテンプレート。
beverage-inventory-ordering-system/python_app/update_shared_folder.ps1 が実績パターン。

守る性質:
  - 配布物（EXE / _internal 等のランタイム）と業務データを分離する。
  - 共有フォルダ全体への robocopy /MIR は使わない。同期するのはランタイム領域だけ。
  - 更新前に業務データ全ファイルの SHA-256 と件数を記録し、更新後に変化していないことを検証する。
  - EXE は temp へコピー → Move で atomic に差し替える。
  - 配布先パスは推測・保存しない。実行時に貼り付けてもらう。
  - Windows PowerShell 5.1 互換・UTF-8 ログ。

<...> を対象アプリの実値へ置き換える。
#>
param(
    [string]$TargetPath = "",
    [string]$SourcePath = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- 対象アプリ固有の値 ---
$AppExeName   = "<AppName>.exe"
$BuildDirName = "dist\<AppName>"          # ビルド成果物のフォルダ
$RuntimeDir   = "_internal"                # 完全同期してよいランタイム領域
$DataDirName  = "data"                     # 業務データ領域（更新しない・検証する）
# --------------------------

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
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "業務データが消えました: $DataDirName\$relative" }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $Before[$relative]) {
            throw "業務データが変化しました: $DataDirName\$relative"
        }
    }
    $after = if (Test-Path -LiteralPath $DataPath) { @(Get-ChildItem -LiteralPath $DataPath -File -Recurse -Force) } else { @() }
    if ($after.Count -ne $Before.Count) { throw "業務データのファイル件数が変化しました。" }
}

try {
    Set-Content -LiteralPath $Log -Value "<app-name> shared-folder update" -Encoding UTF8
    Write-UpdateLog ("date:   " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    Write-UpdateLog ("source: " + $Source)

    $sourceExe      = Join-Path $Source $AppExeName
    $sourceRuntime  = Join-Path $Source $RuntimeDir
    if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf))          { throw "ソース EXE がありません。先に BUILD_EXE_CLICK_ME.cmd を実行してください。配布先は変更していません。" }
    if (-not (Test-Path -LiteralPath $sourceRuntime -PathType Container)) { throw "ソース $RuntimeDir がありません。配布先は変更していません。" }

    if (-not $TargetPath) {
        Add-Type -AssemblyName Microsoft.VisualBasic
        $TargetPath = [Microsoft.VisualBasic.Interaction]::InputBox(
            "配布先の <app-name> フォルダのパスをそのまま貼り付けてください。このスクリプトはパスを推測・保存しません。",
            "配布先フォルダ", "")
        $TargetPath = ($TargetPath -as [string]).Trim().Trim('"')
        if (-not $TargetPath) { throw "キャンセルされました。配布先は変更していません。" }
    }

    $Target = [System.IO.Path]::GetFullPath($TargetPath)
    if (-not (Test-Path -LiteralPath $Target -PathType Container)) { throw "配布先フォルダが見つかりません: $Target" }
    if ([StringComparer]::OrdinalIgnoreCase.Equals($Source.TrimEnd('\'), $Target.TrimEnd('\'))) { throw "ソースと配布先が同じフォルダです。" }

    $targetData = Join-Path $Target $DataDirName
    $dataHashes = Get-DataHashes $targetData
    Write-UpdateLog ("target: " + $Target)
    Write-UpdateLog ("protected data files before update: " + $dataHashes.Count)

    $targetRuntime = Join-Path $Target $RuntimeDir
    if (-not (Test-Path -LiteralPath $targetRuntime)) { New-Item -ItemType Directory -Path $targetRuntime | Out-Null }
    Write-UpdateLog "Synchronize runtime: $RuntimeDir"
    & robocopy $sourceRuntime $targetRuntime /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "$RuntimeDir の同期に失敗しました（robocopy exit $LASTEXITCODE）" }

    Write-UpdateLog "Update $AppExeName"
    $targetExe = Join-Path $Target $AppExeName
    $tempExe   = Join-Path $Target (".{0}.update" -f $AppExeName)
    Copy-Item -LiteralPath $sourceExe -Destination $tempExe -Force
    Move-Item -LiteralPath $tempExe -Destination $targetExe -Force

    Assert-DataUnchanged $targetData $dataHashes
    Write-UpdateLog ("operational data SHA-256 verified: " + $dataHashes.Count + " files")
    Write-UpdateLog ("target EXE SHA-256: " + (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash)
    Write-UpdateLog "DONE"
    exit 0
} catch {
    Write-Host ("[ERROR] " + $_.Exception.Message) -ForegroundColor Red
    try { Add-Content -LiteralPath $Log -Value ("ERROR: " + $_.Exception.Message) -Encoding UTF8 } catch {}
    exit 1
}
