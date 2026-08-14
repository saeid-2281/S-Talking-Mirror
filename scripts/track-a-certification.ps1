param(
    [string]$Python = ".venv/Scripts/python.exe",
    [Parameter(Mandatory = $true)][string]$ProductSourceCommit,
    [string]$CertificationCommit = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

if ([string]::IsNullOrWhiteSpace($CertificationCommit)) {
    $CertificationCommit = (& git rev-parse HEAD).Trim()
}

$Branch = (& git branch --show-current).Trim()
$CurrentHead = (& git rev-parse HEAD).Trim()
$AcceptancePath = Join-Path $ProjectRoot "artifacts/track-a-product-acceptance/latest.json"
$FullGatePath = Join-Path $ProjectRoot "artifacts/quality-gate-performance/serial-latest.json"
$OutputRoot = Join-Path $ProjectRoot "artifacts/track-a-certification"
$JsonPath = Join-Path $OutputRoot "latest.json"
$MarkdownPath = Join-Path $OutputRoot "latest.md"
$ShaPath = Join-Path $OutputRoot "latest.sha256.txt"

$RequiredPackaging = @(
    "packaging/S-Talking.spec",
    "app/frozen_main.py",
    "scripts/final-release.ps1",
    "scripts/release-check.ps1"
)
$AuthorityFiles = @(
    "app/models/launch_assurance.py",
    "app/services/launch_assurance_service.py",
    "app/services/preflight_service.py",
    "app/gui/main.py",
    "app/services/pronunciation_readiness_service.py",
    "app/services/pronunciation_audit_service.py"
)

if (-not (Test-Path -LiteralPath $AcceptancePath -PathType Leaf)) {
    throw "Track A7.8 acceptance evidence is missing: $AcceptancePath"
}
if (-not (Test-Path -LiteralPath $FullGatePath -PathType Leaf)) {
    throw "Full Quality Gate evidence is missing: $FullGatePath"
}

$Acceptance = Get-Content -LiteralPath $AcceptancePath -Raw | ConvertFrom-Json
$FullGate = Get-Content -LiteralPath $FullGatePath -Raw | ConvertFrom-Json

if ([string]$Acceptance.status -ne "passed") { throw "A7.8 acceptance evidence is not passed." }
if ([string]$Acceptance.accepted_commit -ne $ProductSourceCommit) {
    throw "A7.8 acceptance evidence accepted_commit mismatch."
}
if (@($Acceptance.scenarios).Count -ne 8) { throw "A7.8 acceptance evidence does not contain 8 lanes." }
if ([int]$Acceptance.total_acceptance_tests -lt 579) { throw "A7.8 acceptance test count is below 579." }
if ([int]$Acceptance.database_schema -ne 23) { throw "A7.8 database schema evidence is not 23." }
if ([bool]$Acceptance.live_synthesis_performed) { throw "A7.8 evidence reports live synthesis." }
if ([bool]$Acceptance.automatic_preflight) { throw "A7.8 evidence reports automatic Preflight." }
if ([bool]$Acceptance.automatic_generation) { throw "A7.8 evidence reports automatic generation." }
if ([bool]$Acceptance.automatic_smart_routing_apply) { throw "A7.8 evidence reports automatic Smart Routing apply." }
if ([bool]$Acceptance.hidden_cross_provider_failover) { throw "A7.8 evidence reports hidden cross-provider failover." }

if (-not [bool]$FullGate.success) { throw "Full Quality Gate evidence is not successful." }
if ([int]$FullGate.failures -ne 0 -or [int]$FullGate.errors -ne 0) {
    throw "Full Quality Gate evidence contains failures/errors."
}
if ([int]$FullGate.tests -lt 1783) { throw "Full Quality Gate test count is below the A7.8 baseline." }

foreach ($Rel in $RequiredPackaging) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $Rel) -PathType Leaf)) {
        throw "Required release/packaging path is missing: $Rel"
    }
    & git ls-files --error-unmatch -- $Rel *> $null
    if ($LASTEXITCODE -ne 0) { throw "Required release/packaging path is not tracked: $Rel" }
}

$ProductAppTree = (& git rev-parse "${ProductSourceCommit}:app").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ProductAppTree)) { throw "Unable to resolve product app tree." }
$CurrentAppTree = (& git rev-parse "HEAD:app").Trim()
if ($CurrentAppTree -ne $ProductAppTree) { throw "Application tree changed after the certified A7.8 product source." }

$ProductPackagingTree = (& git rev-parse "${ProductSourceCommit}:packaging").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ProductPackagingTree)) { throw "Unable to resolve product packaging tree." }
$CurrentPackagingTree = (& git rev-parse "HEAD:packaging").Trim()
if ($CurrentPackagingTree -ne $ProductPackagingTree) { throw "Packaging tree changed after the certified A7.8 product source." }

$AuthorityHashes = [ordered]@{}
foreach ($Rel in $AuthorityFiles) {
    $Full = Join-Path $ProjectRoot $Rel
    if (-not (Test-Path -LiteralPath $Full -PathType Leaf)) { throw "Authority freeze file is missing: $Rel" }
    $AuthorityHashes[$Rel] = (Get-FileHash -LiteralPath $Full -Algorithm SHA256).Hash.ToLowerInvariant()
}

$PyInstallerVersion = (& $Python -m PyInstaller --version).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($PyInstallerVersion)) {
    throw "PyInstaller packaging tool is unavailable."
}

$AcceptanceHash = (Get-FileHash -LiteralPath $AcceptancePath -Algorithm SHA256).Hash.ToLowerInvariant()
$FullGateHash = (Get-FileHash -LiteralPath $FullGatePath -Algorithm SHA256).Hash.ToLowerInvariant()
$GeneratedUtc = [DateTime]::UtcNow.ToString("o")

$Attestation = [ordered]@{
    schema_version = 1
    roadmap = "Roadmap 2"
    track = "A"
    phase = "A7.9"
    title = "Track A Certification & Freeze"
    status = "certified"
    branch = $Branch
    product_source_commit = $ProductSourceCommit
    certification_commit = $CertificationCommit
    current_head = $CurrentHead
    generated_utc = $GeneratedUtc
    acceptance = [ordered]@{
        source = "artifacts/track-a-product-acceptance/latest.json"
        sha256 = $AcceptanceHash
        status = [string]$Acceptance.status
        accepted_commit = [string]$Acceptance.accepted_commit
        lanes = @($Acceptance.scenarios).Count
        tests = [int]$Acceptance.total_acceptance_tests
        live_synthesis_performed = [bool]$Acceptance.live_synthesis_performed
    }
    quality_gate = [ordered]@{
        source = "artifacts/quality-gate-performance/serial-latest.json"
        sha256 = $FullGateHash
        success = [bool]$FullGate.success
        tests = [int]$FullGate.tests
        passed = [int]$FullGate.passed
        skipped = [int]$FullGate.skipped
        failures = [int]$FullGate.failures
        errors = [int]$FullGate.errors
        elapsed_seconds = [double]$FullGate.elapsed_seconds
    }
    database_schema = 23
    authority_freeze = [ordered]@{
        user_selected_target_language = "authoritative"
        per_job_explicit_language_override = "authoritative"
        content_based_language_detection_override = $false
        automatic_provider_account_voice_model_language_change = $false
        automatic_preflight = $false
        automatic_generation = $false
        automatic_smart_routing_apply = $false
        hidden_cross_provider_failover = $false
        source_text_mutation_introduced = $false
        generation_authority_added_by_certification = $false
    }
    architecture_freeze = [ordered]@{
        app_tree = $ProductAppTree
        packaging_tree = $ProductPackagingTree
        authority_file_sha256 = $AuthorityHashes
    }
    release_packaging = [ordered]@{
        pyinstaller_version = $PyInstallerVersion
        spec = "packaging/S-Talking.spec"
        frozen_entrypoint = "app/frozen_main.py"
        final_release_script = "scripts/final-release.ps1"
        release_check_script = "scripts/release-check.ps1"
        compiled_installer_required_for_track_a_freeze = $false
        signing_required_for_track_a_freeze = $false
    }
    privacy = [ordered]@{
        credentials_in_attestation = $false
        raw_source_text_in_attestation = $false
        raw_voice_model_dictionary_ids_required = $false
    }
    freeze_policy = [ordered]@{
        track_a_feature_work = "closed"
        product_authority_contracts = "frozen"
        "changes_after_a79_require_explicit_later_roadmap_scope" = "yes"
    }
    next = "Roadmap 2 A8 - Visual Design System 2.0"
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$Attestation | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $JsonPath -Encoding UTF8

$Markdown = @"
# S-Talking Roadmap 2 — Track A Certification & Freeze

- Status: **CERTIFIED**
- Product source commit: $ProductSourceCommit
- Certification commit: $CertificationCommit
- Application tree: $ProductAppTree
- Packaging tree: $ProductPackagingTree
- A7.8 acceptance: **8/8 lanes, $($Acceptance.total_acceptance_tests) tests**
- Full Quality Gate: **$($FullGate.tests) tests, $($FullGate.failures) failures, $($FullGate.errors) errors**
- Database schema: **23**
- Live synthesis during certification: **No**
- Automatic Preflight / generation / Smart Routing apply: **Disabled**
- Hidden cross-provider failover: **Not introduced**
- User-selected language and per-job explicit language override: **Authoritative**
- Release packaging contract: **Tracked and structurally verified**
- PyInstaller: $PyInstallerVersion

Track A feature work is frozen at this product source. A7.9 adds certification evidence only and does not alter the application or packaging trees.

Next: **Roadmap 2 A8 — Visual Design System 2.0**.
"@
$Markdown | Set-Content -LiteralPath $MarkdownPath -Encoding UTF8

$JsonSha = (Get-FileHash -LiteralPath $JsonPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$JsonSha  latest.json" | Set-Content -LiteralPath $ShaPath -Encoding ASCII

$RoundTrip = Get-Content -LiteralPath $JsonPath -Raw | ConvertFrom-Json
if ([string]$RoundTrip.status -ne "certified") { throw "Track A attestation round-trip verification failed." }
if ([string]$RoundTrip.product_source_commit -ne $ProductSourceCommit) { throw "Track A product-source provenance verification failed." }
if ([string]$RoundTrip.certification_commit -ne $CertificationCommit) { throw "Track A certification-commit provenance verification failed." }
if ([string]$RoundTrip.architecture_freeze.app_tree -ne $ProductAppTree) { throw "Track A app-tree freeze verification failed." }
if ([int]$RoundTrip.acceptance.lanes -ne 8 -or [int]$RoundTrip.acceptance.tests -lt 579) { throw "Track A acceptance reuse verification failed." }

Write-Host "Track A certification status: CERTIFIED" -ForegroundColor Green
Write-Host "Product source commit: $ProductSourceCommit" -ForegroundColor Green
Write-Host "Certification commit: $CertificationCommit" -ForegroundColor Green
Write-Host "Application tree freeze: $ProductAppTree" -ForegroundColor Green
Write-Host "Packaging tree freeze: $ProductPackagingTree" -ForegroundColor Green
Write-Host "Acceptance evidence: 8/8 lanes / $($Acceptance.total_acceptance_tests) tests" -ForegroundColor Green
Write-Host "Full Quality Gate evidence: $($FullGate.tests) tests" -ForegroundColor Green
Write-Host "Attestation: $JsonPath" -ForegroundColor Green
Write-Host "Attestation SHA-256: $JsonSha" -ForegroundColor Green
