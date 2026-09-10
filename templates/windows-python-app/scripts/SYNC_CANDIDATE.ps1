param(
    [Parameter(Mandatory = $false)]
    [string]$ExpectedSha = "",

    [Parameter(Mandatory = $true)]
    [string]$ExpectedRepo,

    [Parameter(Mandatory = $true)]
    [string]$TargetBranch
)

Set-StrictMode -Version 2.0

function Invoke-Git {
    param([string[]]$Arguments)

    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git -C $script:RepoRoot @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }

    if ($exitCode -ne 0) {
        $text = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        throw "git $($Arguments -join ' ') failed with exit code $exitCode`n$text"
    }

    return @($output | ForEach-Object { $_.ToString() })
}

function Get-RepoSlug {
    param([string]$RemoteUrl)

    $match = [regex]::Match($RemoteUrl.Trim(), 'github\.com[:/](?<slug>[^/]+/[^/]+?)(?:\.git)?$')
    if (-not $match.Success) {
        return ""
    }

    return $match.Groups['slug'].Value.TrimEnd('/')
}

function Write-Result {
    param(
        [string]$State,
        [string]$Reason,
        [string]$Branch = "",
        [string]$LocalHead = "",
        [string]$OriginHead = "",
        [string]$Expected = "",
        [string]$Match = "NO",
        [string]$TrackedDirty = "UNKNOWN",
        [int]$UntrackedCount = 0,
        [int]$Ahead = -1,
        [int]$Behind = -1
    )

    $lines = @(
        "state: $State",
        "reason: $Reason",
        "repo: $ExpectedRepo",
        "branch: $Branch",
        "local HEAD: $LocalHead",
        "origin HEAD: $OriginHead",
        "expected SHA: $Expected",
        "match: $Match",
        "tracked dirty: $TrackedDirty",
        "untracked count: $UntrackedCount",
        "ahead: $Ahead",
        "behind: $Behind"
    )

    $lines | Set-Content -LiteralPath $script:ResultPath -Encoding ASCII
    $lines | ForEach-Object { Write-Host $_ }
}

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

try {
    $probe = & git -C $scriptDir rev-parse --show-toplevel 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "This script is not inside a Git working tree."
    }
    $script:RepoRoot = ($probe | Select-Object -First 1).ToString().Trim()
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    exit 2
}

$script:ResultPath = Join-Path $script:RepoRoot "SYNC_RESULT.txt"

$branch = ""
$localHead = ""
$originHead = ""
$resolvedExpected = ""
$trackedDirty = "UNKNOWN"
$untrackedCount = 0
$ahead = -1
$behind = -1

try {
    $inside = (Invoke-Git @("rev-parse", "--is-inside-work-tree") | Select-Object -First 1).Trim()
    if ($inside -ne "true") {
        throw "Not inside a Git working tree."
    }

    $originUrl = (Invoke-Git @("remote", "get-url", "origin") | Select-Object -First 1).Trim()
    $actualRepo = Get-RepoSlug $originUrl
    if ([string]::IsNullOrWhiteSpace($actualRepo)) {
        throw "origin is not a recognized github.com repository URL: $originUrl"
    }
    if (-not $actualRepo.Equals($ExpectedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Wrong repository. Expected $ExpectedRepo but origin is $actualRepo."
    }

    $branch = (Invoke-Git @("branch", "--show-current") | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw "Detached HEAD detected. No automatic switch will be performed."
    }
    if ($branch -ne $TargetBranch) {
        throw "Wrong branch. Expected $TargetBranch but current branch is $branch. No automatic switch will be performed."
    }

    $trackedLines = @(Invoke-Git @("status", "--porcelain", "--untracked-files=no") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($trackedLines.Count -gt 0) {
        $trackedDirty = "YES"
        throw "Tracked working-tree changes exist. Nothing was changed."
    }
    $trackedDirty = "NO"

    $allStatus = @(Invoke-Git @("status", "--porcelain", "--untracked-files=all") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $untracked = @($allStatus | Where-Object { $_ -like "?? *" -and $_ -ne "?? SYNC_RESULT.txt" })
    $untrackedCount = $untracked.Count
    if ($untrackedCount -gt 0) {
        Write-Host "WARNING: $untrackedCount untracked item(s) exist. They will not be modified."
    }

    if ([string]::IsNullOrWhiteSpace($ExpectedSha)) {
        $ExpectedSha = Read-Host "Paste expected candidate SHA"
    }
    $ExpectedSha = $ExpectedSha.Trim()
    if ($ExpectedSha -notmatch '^[0-9a-fA-F]{7,40}$') {
        throw "Expected SHA must be 7 to 40 hexadecimal characters."
    }

    Write-Host "Fetching origin/$TargetBranch ..."
    [void](Invoke-Git @("fetch", "--prune", "origin", $TargetBranch))

    $originRef = "refs/remotes/origin/$TargetBranch"
    $originHead = (Invoke-Git @("rev-parse", $originRef) | Select-Object -First 1).Trim()
    $resolvedExpected = (Invoke-Git @("rev-parse", "$ExpectedSha^{commit}") | Select-Object -First 1).Trim()

    if ($originHead -ne $resolvedExpected) {
        throw "origin/$TargetBranch is $originHead, not the expected candidate $resolvedExpected. Refusing to sync a different commit."
    }

    $localHead = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
    $ahead = [int]((Invoke-Git @("rev-list", "--count", "$originHead..HEAD") | Select-Object -First 1).Trim())
    $behind = [int]((Invoke-Git @("rev-list", "--count", "HEAD..$originHead") | Select-Object -First 1).Trim())

    if ($ahead -gt 0) {
        throw "Local branch is ahead of origin/$TargetBranch by $ahead commit(s). Refusing to overwrite or rewrite local work."
    }

    if ($behind -gt 0) {
        Write-Host "Fast-forwarding to the verified candidate ..."
        [void](Invoke-Git @("merge", "--ff-only", $originRef))
    }

    $localHead = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
    $originHead = (Invoke-Git @("rev-parse", $originRef) | Select-Object -First 1).Trim()
    $ahead = [int]((Invoke-Git @("rev-list", "--count", "$originHead..HEAD") | Select-Object -First 1).Trim())
    $behind = [int]((Invoke-Git @("rev-list", "--count", "HEAD..$originHead") | Select-Object -First 1).Trim())

    $trackedLines = @(Invoke-Git @("status", "--porcelain", "--untracked-files=no") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $trackedDirty = if ($trackedLines.Count -gt 0) { "YES" } else { "NO" }

    if ($trackedDirty -ne "NO") {
        throw "Tracked working tree became dirty after sync."
    }
    if ($localHead -ne $resolvedExpected -or $originHead -ne $resolvedExpected) {
        throw "Post-sync SHA verification failed."
    }

    Write-Result -State "SUCCESS" -Reason "candidate synchronized and verified" -Branch $branch -LocalHead $localHead -OriginHead $originHead -Expected $resolvedExpected -Match "YES" -TrackedDirty $trackedDirty -UntrackedCount $untrackedCount -Ahead $ahead -Behind $behind
    exit 0
}
catch {
    $reason = $_.Exception.Message
    try {
        if (-not [string]::IsNullOrWhiteSpace($script:RepoRoot)) {
            if ([string]::IsNullOrWhiteSpace($localHead)) {
                $localHead = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
            }
        }
    }
    catch {
    }

    Write-Result -State "STOPPED" -Reason $reason -Branch $branch -LocalHead $localHead -OriginHead $originHead -Expected $resolvedExpected -Match "NO" -TrackedDirty $trackedDirty -UntrackedCount $untrackedCount -Ahead $ahead -Behind $behind
    exit 1
}
