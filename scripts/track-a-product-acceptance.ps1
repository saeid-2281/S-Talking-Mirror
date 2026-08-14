[CmdletBinding()]
param(
    [string]$Python = ".venv/Scripts/python.exe",
    [string]$OutputRoot = "artifacts/track-a-product-acceptance"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$PythonPath = if ([System.IO.Path]::IsPathRooted($Python)) { $Python } else { Join-Path $ProjectRoot $Python }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python environment not found: $PythonPath"
}

$SourceCommit = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($SourceCommit)) {
    throw "Unable to determine Track A acceptance source commit."
}

$RunId = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputRootPath = if ([System.IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot } else { Join-Path $ProjectRoot $OutputRoot }
$RunRoot = Join-Path $OutputRootPath "runs/$RunId"
$LatestPath = Join-Path $OutputRootPath "latest.json"
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null

function Existing-Tests([string[]]$Candidates) {
    return @(
        foreach ($Candidate in $Candidates) {
            $FilePart = (($Candidate -split "::", 2)[0]).Replace("/", "\")
            if (Test-Path -LiteralPath (Join-Path $ProjectRoot $FilePart) -PathType Leaf) {
                $Candidate
            }
        }
    ) | Sort-Object -Unique
}

function Discover-TestFiles([string]$Regex) {
    return @(
        Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "tests") -File -Filter "test_*.py" -ErrorAction Stop |
        Where-Object { $_.Name -match $Regex } |
        ForEach-Object { "tests/$($_.Name)" }
    ) | Sort-Object -Unique
}

function Read-JUnitCounts([string]$Path) {
    [xml]$Xml = Get-Content -LiteralPath $Path -Raw
    $Suites = @()
    if ($Xml.testsuites) { $Suites = @($Xml.testsuites.testsuite) }
    elseif ($Xml.testsuite) { $Suites = @($Xml.testsuite) }
    if ($Suites.Count -eq 0) { throw "No testsuite element in JUnit evidence: $Path" }
    $Tests = 0; $Failures = 0; $Errors = 0; $Skipped = 0; $Time = 0.0
    foreach ($Suite in $Suites) {
        $Tests += [int]$Suite.tests
        $Failures += [int]$Suite.failures
        $Errors += [int]$Suite.errors
        if ($null -ne $Suite.skipped) { $Skipped += [int]$Suite.skipped }
        if ($null -ne $Suite.time) { $Time += [double]$Suite.time }
    }
    return [ordered]@{
        tests = $Tests
        failures = $Failures
        errors = $Errors
        skipped = $Skipped
        duration_seconds = [math]::Round($Time, 3)
    }
}

$ScenarioResults = New-Object System.Collections.Generic.List[object]
function Run-AcceptanceLane(
    [string]$Label,
    [string]$Slug,
    [string[]]$Candidates,
    [int]$MinimumTests = 1
) {
    $Tests = Existing-Tests $Candidates
    if ($Tests.Count -lt 1) { throw "Acceptance lane '$Label' has no matching tests." }
    $Junit = Join-Path $RunRoot "$Slug.xml"
    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $PythonPath -m pytest @Tests -q "--junitxml=$Junit"
    if ($LASTEXITCODE -ne 0) { throw "Acceptance lane failed: $Label" }
    $Counts = Read-JUnitCounts $Junit
    if ([int]$Counts.tests -lt $MinimumTests) { throw "Acceptance lane '$Label' executed fewer than $MinimumTests tests." }
    if ([int]$Counts.failures -ne 0 -or [int]$Counts.errors -ne 0) { throw "Acceptance lane '$Label' has JUnit failures/errors." }
    $ScenarioResults.Add([pscustomobject][ordered]@{
        label = $Label
        slug = $Slug
        status = "passed"
        test_targets = @($Tests)
        tests = [int]$Counts.tests
        skipped = [int]$Counts.skipped
        failures = [int]$Counts.failures
        errors = [int]$Counts.errors
        duration_seconds = [double]$Counts.duration_seconds
        junit = (Resolve-Path -LiteralPath $Junit).Path.Substring($ProjectRoot.Length).TrimStart("\").Replace("\", "/")
    })
}

$A2A4 = @(
    "tests/test_first_run_onboarding_experience_roadmap2_a2.py",
    "tests/test_provider_setup_wizard_roadmap2_a3.py",
    "tests/test_voice_model_discovery_selection_ux_roadmap2_a4.py"
)
$SourceQueue = @(
    "tests/test_csv_loader.py",
    "tests/test_csv_repair_workflow.py",
    "tests/test_batch_generation_planning_ux_phase34.py",
    "tests/test_text_source_batch_preparation_phase91.py",
    "tests/test_queue_batch_operations_phase92.py"
)
$A7Series = @(
    "tests/test_preflight_decision_launch_readiness_experience_roadmap2_a7.py",
    "tests/test_language_lock_provider_enforcement_roadmap2_a71.py",
    "tests/test_short_utterance_pronunciation_hardening_roadmap2_a72.py",
    "tests/test_pronunciation_review_workspace_roadmap2_a73.py",
    "tests/test_pronunciation_decision_freshness_revalidation_roadmap2_a74.py",
    "tests/test_pronunciation_decision_audit_trail_evidence_roadmap2_a75.py",
    "tests/test_pronunciation_coverage_project_readiness_roadmap2_a76.py",
    "tests/test_launch_assurance_consolidation_roadmap2_a77.py"
)
$GenerationLifecycle = @(
    "tests/test_generation_engine_v07.py",
    "tests/test_generation_monitor_pro.py",
    "tests/test_generation_history_ux_phase30.py"
) + (Discover-TestFiles '^test_.*(launch|execution.*session|execution.*receipt|safe.*resume|recovery).*\.py$')
$OutputReview = @(
    "tests/test_audio_output_playback_ux_phase32.py",
    "tests/test_audio_player_v09.py",
    "tests/test_audio_review_export_ux_phase94.py",
    "tests/test_dashboard_reports.py"
)
$ProviderMatrix = @(
    "tests/test_danish_provider_benchmark_certification_phase109.py",
    "tests/test_user_controlled_multi_provider_recovery_phase110.py",
    "tests/test_smart_provider_routing_phase98.py"
) + (Discover-TestFiles '^test_.*(provider|cloud|local).*phase10[0-4].*\.py$')
$LargeMixed = @(
    "tests/test_track_a_end_to_end_product_acceptance_roadmap2_a78.py::test_a78_large_batch_4001_revision_is_deterministic_and_non_mutating",
    "tests/test_track_a_end_to_end_product_acceptance_roadmap2_a78.py::test_a78_explicit_mixed_language_overrides_are_revision_authoritative",
    "tests/test_track_a_end_to_end_product_acceptance_roadmap2_a78.py::test_a78_cloud_and_local_provider_contexts_remain_explicitly_distinct",
    "tests/test_track_a_end_to_end_product_acceptance_roadmap2_a78.py::test_a78_launch_assurance_accepts_same_large_batch_evidence_across_all_checkpoints"
)
$ReleaseQProcess = @(
    "tests/test_devtools_diagnostics.py::test_qprocess_runner_captures_success",
    "tests/test_devtools_diagnostics.py::test_qprocess_runner_captures_failure",
    "tests/test_release_candidate_v013.py::test_release_check_script_and_packaging_config_exist",
    "tests/test_ux_accessibility_theme_certification_phase59.py::test_phase59_cli_script_theme_and_privacy_contracts",
    "tests/test_final_production_certification_phase88.py"
)

try {
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "Roadmap 2 A7.8 — Track A Product Acceptance" -ForegroundColor Cyan
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "Source commit: $SourceCommit"
    Write-Host "Evidence root: $RunRoot"
    Write-Host "Acceptance-only harness; no synthesis or source mutation." -ForegroundColor DarkGray

    Run-AcceptanceLane "First-run / provider / voice-model" "01-first-run-provider" $A2A4 3
    Run-AcceptanceLane "Text-source / queue / batch preparation" "02-source-queue" $SourceQueue 3
    Run-AcceptanceLane "Pronunciation / Preflight / launch assurance" "03-pronunciation-preflight-launch" $A7Series 8
    Run-AcceptanceLane "Generation lifecycle / pause-resume-stop / recovery" "04-generation-lifecycle" $GenerationLifecycle 2
    Run-AcceptanceLane "Audio output / review / export" "05-output-review-export" $OutputReview 2
    Run-AcceptanceLane "Cloud-local provider matrix / Danish authority" "06-provider-matrix" $ProviderMatrix 3
    Run-AcceptanceLane "4001-row / mixed-language acceptance" "07-large-mixed" $LargeMixed 4
    Run-AcceptanceLane "QProcess / release compatibility" "08-release-qprocess" $ReleaseQProcess 4

    # PowerShell 5.1 can throw "Argument types do not match" when an
    # array subexpression directly wraps Generic.List[object] containing
    # PSCustomObject values. Materialize a real Object[] once and reuse it
    # for aggregation and JSON serialization.
    $ScenarioSnapshot = $ScenarioResults.ToArray()
    $TotalTests = [int](($ScenarioSnapshot | Measure-Object -Property tests -Sum).Sum)
    $TotalSkipped = [int](($ScenarioSnapshot | Measure-Object -Property skipped -Sum).Sum)
    $Report = [ordered]@{
        schema_version = 1
        phase = "A7.8"
        status = "passed"
        source_commit = $SourceCommit
        accepted_commit = $null
        created_utc = (Get-Date).ToUniversalTime().ToString("o")
        privacy_safe = $true
        live_synthesis_performed = $false
        automatic_preflight = $false
        automatic_generation = $false
        automatic_smart_routing_apply = $false
        hidden_cross_provider_failover = $false
        database_schema = 23
        total_acceptance_tests = $TotalTests
        total_skipped = $TotalSkipped
        scenarios = $ScenarioSnapshot
    }
    $Json = $Report | ConvertTo-Json -Depth 8
    $RunReport = Join-Path $RunRoot "result.json"
    $Json | Set-Content -LiteralPath $RunReport -Encoding UTF8
    New-Item -ItemType Directory -Path $OutputRootPath -Force | Out-Null
    $Json | Set-Content -LiteralPath $LatestPath -Encoding UTF8

    Write-Host ""
    Write-Host "Track A product acceptance: PASSED" -ForegroundColor Green
    Write-Host "Acceptance lanes: 8/8 PASSED" -ForegroundColor Green
    Write-Host "Acceptance tests: $TotalTests" -ForegroundColor Green
    Write-Host "Evidence: $LatestPath" -ForegroundColor Green
    Write-Host "Automatic Preflight: DISABLED" -ForegroundColor Green
    Write-Host "Automatic generation: DISABLED" -ForegroundColor Green
    Write-Host "Automatic Smart Routing apply: DISABLED" -ForegroundColor Green
    Write-Host "Hidden cross-provider failover: NOT INTRODUCED" -ForegroundColor Green
    Write-Host "Database schema 23: PRESERVED" -ForegroundColor Green
}
catch {
    # Use the same explicit List[object] -> Object[] conversion on failure so
    # evidence generation cannot mask the original acceptance error.
    $FailureScenarioSnapshot = $ScenarioResults.ToArray()
    $Failure = [ordered]@{
        schema_version = 1
        phase = "A7.8"
        status = "failed"
        source_commit = $SourceCommit
        created_utc = (Get-Date).ToUniversalTime().ToString("o")
        privacy_safe = $true
        error = $_.Exception.Message
        scenarios = $FailureScenarioSnapshot
    }
    $Failure | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $LatestPath -Encoding UTF8
    throw
}
