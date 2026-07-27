$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$path = Join-Path $root "app\gui\main.py"

if (-not (Test-Path $path)) {
    throw "main.py not found: $path"
}

$text = Get-Content -Path $path -Raw -Encoding UTF8
$old = "from app.gui.widgets import ControlledDoubleSpinBox, ControlledSpinBox"
$new = "from app.gui.widgets import ControlledSpinBox"

if ($text -notmatch [regex]::Escape($old)) {
    if ($text -match [regex]::Escape($new)) {
        Write-Host "No change needed. Import is already fixed."
        exit 0
    }
    throw "Expected import line was not found. No file was changed."
}

$backup = "$path.bak-before-unused-import-fix"
Copy-Item -Path $path -Destination $backup -Force
$text = $text.Replace($old, $new)
Set-Content -Path $path -Value $text -Encoding UTF8

Write-Host "Updated: $path"
Write-Host "Backup:  $backup"
