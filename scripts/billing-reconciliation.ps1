param(
    [string]$Executable = ".\S-Talking.exe",
    [string[]]$InvoiceRecord = @(),
    [string[]]$ReplayResult = @(),
    [string[]]$ReplayAttestation = @(),
    [string[]]$ReplayPack = @(),
    [string[]]$ReplayReceipt = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Arguments = @("--billing-reconciliation-snapshot")
foreach ($Path in $InvoiceRecord) { $Arguments += @("--billing-invoice-record", $Path) }
foreach ($Path in $ReplayResult) { $Arguments += @("--billing-replay-result", $Path) }
foreach ($Path in $ReplayAttestation) { $Arguments += @("--billing-replay-attestation", $Path) }
foreach ($Path in $ReplayPack) { $Arguments += @("--billing-replay-pack", $Path) }
foreach ($Path in $ReplayReceipt) { $Arguments += @("--billing-replay-receipt", $Path) }

& $Executable @Arguments
exit $LASTEXITCODE
