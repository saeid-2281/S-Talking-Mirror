param(
    [ValidateSet("ffmpeg", "windows")]
    [string]$MediaBackend = "ffmpeg"
)

& (Join-Path $PSScriptRoot "run.ps1") -Console -MediaBackend $MediaBackend
exit $LASTEXITCODE
