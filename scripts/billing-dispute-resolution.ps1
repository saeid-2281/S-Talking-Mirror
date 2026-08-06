param(
    [string]$Executable = ".\S-Talking.exe",
    [string[]]$Result = @(),
    [string[]]$Attestation = @(),
    [string[]]$DisputePack = @(),
    [string[]]$Receipt = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Arguments = @("--billing-dispute-resolution-snapshot")
foreach ($Path in $Result) { $Arguments += @("--billing-dispute-result", $Path) }
foreach ($Path in $Attestation) {
    $Arguments += @("--billing-dispute-attestation", $Path)
}
foreach ($Path in $DisputePack) {
    $Arguments += @("--billing-dispute-pack", $Path)
}
foreach ($Path in $Receipt) {
    $Arguments += @("--billing-dispute-source-receipt", $Path)
}

& $Executable @Arguments
exit $LASTEXITCODE
