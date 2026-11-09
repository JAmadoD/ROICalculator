# Builds dist\ROICalculator\ROICalculator.exe with PyInstaller.
# Run from the project folder, ideally inside a virtual environment.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

python -m PyInstaller --noconfirm --clean ROICalculator.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

Write-Host ""
Write-Host "Build complete:"
Write-Host "dist\ROICalculator\ROICalculator.exe"
