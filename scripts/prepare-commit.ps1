$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$OutDir = Join-Path $Root "artifacts\prepare-commit"
$Summary = Join-Path $OutDir "latest.txt"

New-Item -ItemType Directory -Force $OutDir | Out-Null
"S Talking prepare commit dry run" | Set-Content $Summary
"Started: $(Get-Date -Format o)" | Add-Content $Summary

$Branch = git branch --show-current
"Branch: $Branch" | Add-Content $Summary
if ($Branch -eq "main") {
    "ERROR: Refusing to prepare a commit on main." | Add-Content $Summary
    exit 1
}

"Changed files:" | Add-Content $Summary
git status --short | Add-Content $Summary

"Suggested message:" | Add-Content $Summary
"feat(ux): automate workflow, dashboard, and generation reports" | Add-Content $Summary

"Checks are intentionally previewed through scripts/dev-check.ps1 before real commit actions." | Add-Content $Summary
Write-Host "Prepare Commit dry run written to $Summary"
