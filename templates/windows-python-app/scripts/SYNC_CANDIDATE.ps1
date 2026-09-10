param(
    [string]$ExpectedSha = "",
    [Parameter(Mandatory = $true)][string]$ExpectedRepo,
    [Parameter(Mandatory = $true)][string]$TargetBranch
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Run-Git {
    param([string[]]$GitArgs)

    $output = & git -C $script:RepoRoot @GitArgs 2>&1
    $code = $LASTEXITCODE
    $items = @($output | ForEach-Object { $_.ToString() })
    if ($code -ne 0) {
        throw "git $($GitArgs -join ' ') failed with exit code $code`n$($items -join [Environment]::NewLine)"
    }
    return $items
}

function Write-SyncResult {
    param(
        [string]$State,
        [string]$Reason,
        [string]$Branch,
        [string]$LocalHead,
        [string]$OriginHead,
        [string]$Expected,
        [string]$Match,
        [string]$TrackedDirty,
        [int]$UntrackedCount,
        [int]$Ahead,
        [int]$Behind
    )

    $lines = @(
        "state: $State"
        "reason: $Reason"
        "repo: $ExpectedRepo"
        "branch: $Branch"
        "local HEAD: $LocalHead"
        "origin HEAD: $OriginHead"
        "expected SHA: $Expected"
        "match: $Match"
        "tracked dirty: $TrackedDirty"
        "untracked count: $UntrackedCount"
        "ahead: $Ahead"
        "behind: $Behind"
    )
    $lines | Set-Content -LiteralPath $script:ResultPath -Encoding ASCII
    $lines | ForEach-Object { Write-Host $_ }
}

$probe = & git -C $PSScriptRoot rev-parse --show-toplevel 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: This script is not inside a Git working tree."
    exit 2
}

$script:RepoRoot = ($probe | Select-Object -First 1).ToString().Trim()
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
    $inside = (Run-Git @("rev-parse", "--is-inside-work-tree") | Select-Object -First 1).Trim()
    if ($inside -ne "true") { throw "Not inside a Git working tree." }

    $originUrl = (Run-Git @("remote", "get-url", "origin") | Select-Object -First 1).Trim()
    if ($originUrl -notmatch 'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$') {
        throw "origin is not a recognized github.com repository URL: $originUrl"
    }
    $actualRepo = $Matches[1]
    if (-not $actualRepo.Equals($ExpectedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Wrong repository. Expected $ExpectedRepo but origin is $actualRepo."
    }

    $branch = (Run-Git @("branch", "--show-current") | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw "Detached HEAD detected. No automatic switch will be performed."
    }
    if ($branch -ne $TargetBranch) {
        throw "Wrong branch. Expected $TargetBranch but current branch is $branch. No automatic switch will be performed."
    }

    $tracked = @(Run-Git @("status", "--porcelain", "--untracked-files=no") | Where-Object { $_ })
    if ($tracked.Count -gt 0) {
        $trackedDirty = "YES"
        throw "Tracked working-tree changes exist. Nothing was changed."
    }
    $trackedDirty = "NO"

    $untracked = @(Run-Git @("status", "--porcelain", "--untracked-files=all") | Where-Object { $_ -like "?? *" })
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
    [void](Run-Git @("fetch", "--prune", "origin", $TargetBranch))

    $originRef = "refs/remotes/origin/$TargetBranch"
    $originHead = (Run-Git @("rev-parse", $originRef) | Select-Object -First 1).Trim()
    $resolvedExpected = (Run-Git @("rev-parse", "$ExpectedSha^{commit}") | Select-Object -First 1).Trim()
    if ($originHead -ne $resolvedExpected) {
        throw "origin/$TargetBranch is $originHead, not the expected candidate $resolvedExpected. Refusing to sync a different commit."
    }

    $localHead = (Run-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
    $ahead = [int]((Run-Git @("rev-list", "--count", "$originHead..HEAD") | Select-Object -First 1).Trim())
    $behind = [int]((Run-Git @("rev-list", "--count", "HEAD..$originHead") | Select-Object -First 1).Trim())
    if ($ahead -gt 0) {
        throw "Local branch is ahead of origin/$TargetBranch by $ahead commit(s). Refusing to rewrite local work."
    }

    if ($behind -gt 0) {
        Write-Host "Fast-forwarding to the verified candidate ..."
        [void](Run-Git @("merge", "--ff-only", $originRef))
    }

    $localHead = (Run-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
    $originHead = (Run-Git @("rev-parse", $originRef) | Select-Object -First 1).Trim()
    $ahead = [int]((Run-Git @("rev-list", "--count", "$originHead..HEAD") | Select-Object -First 1).Trim())
    $behind = [int]((Run-Git @("rev-list", "--count", "HEAD..$originHead") | Select-Object -First 1).Trim())
    $tracked = @(Run-Git @("status", "--porcelain", "--untracked-files=no") | Where-Object { $_ })
    $trackedDirty = if ($tracked.Count -gt 0) { "YES" } else { "NO" }

    if ($trackedDirty -ne "NO") { throw "Tracked working tree became dirty after sync." }
    if ($localHead -ne $resolvedExpected -or $originHead -ne $resolvedExpected) {
        throw "Post-sync SHA verification failed."
    }

    Write-SyncResult "SUCCESS" "candidate synchronized and verified" $branch $localHead $originHead $resolvedExpected "YES" $trackedDirty $untrackedCount $ahead $behind
    exit 0
}
catch {
    $reason = $_.Exception.Message
    try {
        if (-not $localHead) { $localHead = (Run-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim() }
    }
    catch { }

    Write-SyncResult "STOPPED" $reason $branch $localHead $originHead $resolvedExpected "NO" $trackedDirty $untrackedCount $ahead $behind
    exit 1
}
