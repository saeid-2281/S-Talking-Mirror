param(
    [Parameter(Mandatory=$true)]
    [string]$Branch
)

$ErrorActionPreference = "Stop"

$Status = git status --porcelain
if ($Status) {
    Write-Host "Working tree is not clean. Commit, stash, or discard your own changes first." -ForegroundColor Red
    exit 1
}

git switch main
git pull --ff-only
git switch -c $Branch
