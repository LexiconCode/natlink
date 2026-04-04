<#
.SYNOPSIS
    Build the natlink Python package (sdist + wheel).

.DESCRIPTION
    Uses the virtual environment at .venv if it exists, otherwise
    falls back to whatever python is on PATH. Uses uv for package
    installation if available (handles venvs without pip).

.EXAMPLE
    .\build_py_package.ps1
#>

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

try {
    # --- Resolve Python ---

    $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $Python = $VenvPython
        Write-Host "Using venv Python: $Python"
    } else {
        $Python = (Get-Command python -ErrorAction Stop).Source
        Write-Host "No .venv found -- using PATH Python: $Python"
    }

    # --- Check for uv ---
    $UseUv = $false
    try {
        $null = Get-Command uv -ErrorAction Stop
        $UseUv = $true
    } catch {}

    # --- Ensure build tool is installed ---

    if ($UseUv) {
        uv pip install build --python $Python --quiet
    } else {
        & $Python -m pip install --upgrade build --quiet
    }
    if ($LASTEXITCODE -ne 0) { throw "Failed to install build tool" }

    # --- Clean previous builds ---

    $DistDir = Join-Path $Root "dist"
    if (Test-Path $DistDir) {
        Write-Host "Cleaning dist/..."
        Remove-Item $DistDir -Recurse -Force
    }

    # --- Build ---

    Write-Host "`nBuilding sdist + wheel...`n"
    & $Python -m build $Root
    if ($LASTEXITCODE -ne 0) { throw "Build failed" }

    # --- Show results ---

    Write-Host "`n=== Packages ==="
    Get-ChildItem $DistDir | ForEach-Object {
        $size = [math]::Round($_.Length / 1024)
        $label = '  ' + $_.Name + '  (' + $size + 'KB)'
        Write-Host $label
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
}
finally {
    if ([Environment]::UserInteractive -and -not $env:CI) {
        Read-Host "`nPress Enter to exit"
    }
}
