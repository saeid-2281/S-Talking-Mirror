param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Continue"
$repo = (Resolve-Path ".").Path
$started = Get-Date
$stamp = $started.ToString("yyyy-MM-dd_HH-mm-ss")
$artifactRoot = Join-Path $repo "artifacts\release-check"
$artifactDir = Join-Path $artifactRoot $stamp
$latestDir = Join-Path $artifactRoot "latest"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
New-Item -ItemType Directory -Force -Path $latestDir | Out-Null

$result = [ordered]@{
    schema_version = 1
    started_at = $started.ToString("o")
    finished_at = $null
    elapsed_seconds = 0
    success = $false
    exit_code = 0
    stage = "starting"
    summary = ""
    artifact_directory = $artifactDir
    application_version = ""
    release_channel = "rc"
    source_commit = ""
    working_tree_clean = $false
    steps = [ordered]@{}
}

$commitText = (& git rev-parse HEAD 2>$null | Out-String).Trim()
$statusText = (& git status --porcelain 2>$null | Out-String).Trim()
$result.source_commit = $commitText
$result.working_tree_clean = (-not $statusText)

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$ArgsList
    )
    $output = Join-Path $artifactDir "$Name.txt"
    Write-Output "==> $Name"
    & $Python @ArgsList *> $output
    $code = $LASTEXITCODE
    Get-Content $output -ErrorAction SilentlyContinue | Write-Output
    $result.steps[$Name] = [ordered]@{
        success = ($code -eq 0)
        exit_code = $code
    }
    if ($Name -eq "pytest") {
        $text = Get-Content $output -Raw -ErrorAction SilentlyContinue
        $passed = 0
        if ($text -match "(\d+) passed") { $passed = [int]$Matches[1] }
        $result.steps[$Name].passed = $passed
    }
    $script:LastStepExitCode = $code
}

$exitCode = 0
$result.stage = "compileall"
Invoke-Step "compileall" @("-m","compileall","app")
if ($script:LastStepExitCode -ne 0) { $exitCode = 1 }
$result.stage = "pytest"
Invoke-Step "pytest" @("-m","pytest")
if ($script:LastStepExitCode -ne 0) { $exitCode = 1 }
$result.stage = "ruff"
Invoke-Step "ruff" @("-m","ruff","check","app","tests")
if ($script:LastStepExitCode -ne 0) { $exitCode = 1 }
$result.stage = "ux_certification"
Invoke-Step "ux_certification" @("-m","app.frozen_main","--ux-certification","--ux-certification-export")
if ($script:LastStepExitCode -ne 0) { $exitCode = 1 }

$smoke = @'
from pathlib import Path
from datetime import datetime, timezone
import json
import app
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.csv_loader import diagnose_csv
from app.models import AppSettings, TTSJob

runtime = RuntimeConfig.from_root(Path.cwd())
container = create_service_container(runtime)
csv_path = Path("input.repaired.csv")
csv_state = diagnose_csv(csv_path)
assert csv_state.valid_rows == 4212
assert csv_state.rejected_rows == 0
jobs = [TTSJob(row_number=2, filename="release-smoke.wav", text="Hej release kandidat.")]
settings = AppSettings(provider="mock", skip_existing=False)
preflight = container.preflight_service.run(jobs=jobs, settings=settings, output_dir=runtime.default_output_dir, csv_path=csv_path, project_name="Release check")
assert preflight.status in {"Ready", "Warnings"}
report = container.report_service.create_generation_report(project=None, settings=settings, jobs=jobs, output_dir=runtime.default_output_dir, summary={"total":1,"completed":0,"failed":0,"skipped":0}, started_at=datetime.now(timezone.utc), log_events=["release smoke"])
bundle = container.diagnostics_service.export_bundle(project=None, dashboard=None, queue_state={"active":False,"paused":False})
assert "sk_test_secret" not in container.report_service.sanitize_text("api_key=sk_test_secret")
payload = {"version": app.__version__, "preflight": preflight.status, "report": str(report.report_dir), "diagnostics": str(bundle)}
Path("artifacts/release-smoke.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
'@
$smokePath = Join-Path $artifactDir "release_smoke.py"
$smoke | Set-Content -Path $smokePath -Encoding UTF8
$result.stage = "release_smoke"
$smokeOutput = Join-Path $artifactDir "release_smoke.txt"
& $Python $smokePath *> $smokeOutput
$smokeCode = $LASTEXITCODE
Get-Content $smokeOutput -ErrorAction SilentlyContinue
$result.steps.release_smoke = [ordered]@{ success = ($smokeCode -eq 0); exit_code = $smokeCode }
if ($smokeCode -ne 0) { $exitCode = 1 }

$versionOutput = & $Python -c "import app; print(app.__version__); print(getattr(app,'__release_channel__',''))"
$result.application_version = $versionOutput[0]
$result.release_channel = $versionOutput[1]
$finished = Get-Date
$result.finished_at = $finished.ToString("o")
$result.elapsed_seconds = [math]::Round(($finished - $started).TotalSeconds, 3)
$result.exit_code = $exitCode
$result.success = ($exitCode -eq 0)
$result.stage = if ($exitCode -eq 0) { "complete" } else { "failed" }
$result.summary = if ($exitCode -eq 0) { "Release checks passed" } else { "Release checks failed" }

$json = $result | ConvertTo-Json -Depth 8
$json | Set-Content -Path (Join-Path $artifactDir "result.json") -Encoding UTF8
Remove-Item -Recurse -Force $latestDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $latestDir | Out-Null
Copy-Item -Path (Join-Path $artifactDir "*") -Destination $latestDir -Recurse -Force
if ($exitCode -eq 0) { "All release checks passed." } else { "Release checks failed." }
exit $exitCode
