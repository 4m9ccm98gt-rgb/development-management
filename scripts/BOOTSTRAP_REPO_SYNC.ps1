param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$ExpectedRepo,
    [Parameter(Mandatory = $true)][string]$TargetBranch,
    [Parameter(Mandatory = $true)][string]$ExpectedSha
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Run-Git {
    param([string[]]$GitArgs)
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git -C $RepoRoot @GitArgs 2>&1
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
    $items = @($output | ForEach-Object { $_.ToString() })
    if ($code -ne 0) {
        throw "git $($GitArgs -join ' ') failed with exit code $code`n$($items -join [Environment]::NewLine)"
    }
    return $items
}

try {
    if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
        throw "Repo path does not exist: $RepoRoot"
    }
    if ($ExpectedSha -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Expected SHA must be exactly 40 hexadecimal characters."
    }

    $inside = (Run-Git @("rev-parse", "--is-inside-work-tree") | Select-Object -First 1).Trim()
    if ($inside -ne "true") { throw "Not inside a Git working tree." }

    $originUrl = (Run-Git @("remote", "get-url", "origin") | Select-Object -First 1).Trim()
    if ($originUrl -notmatch '^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?$') {
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
        throw "Tracked working-tree changes exist. Nothing was changed."
    }

    Write-Host "Fetching origin/$TargetBranch ..."
    [void](Run-Git @("fetch", "--prune", "origin", $TargetBranch))
    $originRef = "refs/remotes/origin/$TargetBranch"
    $originHead = (Run-Git @("rev-parse", $originRef) | Select-Object -First 1).Trim()
    $resolvedExpected = (Run-Git @("rev-parse", "$ExpectedSha^{commit}") | Select-Object -First 1).Trim()
    if ($originHead -ne $resolvedExpected) {
        throw "origin/$TargetBranch is $originHead, not expected candidate $resolvedExpected."
    }

    $localHead = (Run-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
    $ahead = [int]((Run-Git @("rev-list", "--count", "$originHead..HEAD") | Select-Object -First 1).Trim())
    if ($ahead -gt 0) {
        throw "Local branch is ahead of origin/$TargetBranch by $ahead commit(s). Refusing to rewrite local work."
    }

    $behind = [int]((Run-Git @("rev-list", "--count", "HEAD..$originHead") | Select-Object -First 1).Trim())
    if ($behind -gt 0) {
        Write-Host "Bootstrap fast-forwarding to verified candidate ..."
        [void](Run-Git @("merge", "--ff-only", $originRef))
    }

    $localHead = (Run-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
    $tracked = @(Run-Git @("status", "--porcelain", "--untracked-files=no") | Where-Object { $_ })
    if ($tracked.Count -gt 0) { throw "Tracked working tree became dirty after bootstrap sync." }
    if ($localHead -ne $resolvedExpected) { throw "Post-sync SHA verification failed." }

    Write-Host "BOOTSTRAP SYNC SUCCEEDED."
    Write-Host "repo: $ExpectedRepo"
    Write-Host "branch: $branch"
    Write-Host "HEAD: $localHead"
    exit 0
}
catch {
    Write-Host "BOOTSTRAP SYNC STOPPED."
    Write-Host $_.Exception.Message
    exit 1
}
