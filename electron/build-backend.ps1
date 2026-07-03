$ErrorActionPreference = "Stop"

$root = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$pythonCandidates = @(
    $env:PETRELHACKER_PYTHON,
    (Join-Path $root "..\.venv\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe"),
    "python"
) | Where-Object { $_ }

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "python" -or (Test-Path -LiteralPath $candidate)) {
        $pythonExe = $candidate
        break
    }
}

if (-not $pythonExe) {
    throw "Python executable was not found. Set PETRELHACKER_PYTHON or create .venv."
}

$buildRoot = Join-Path $root "build-electron"
$backendDist = Join-Path $buildRoot "backend"
$backendWork = Join-Path $buildRoot "pyinstaller-work"
$specPath = $buildRoot

New-Item -ItemType Directory -Force -Path $buildRoot, $backendDist, $backendWork | Out-Null

$backendOutput = Join-Path $backendDist "petrelhacker-backend"
$backendWorkOutput = Join-Path $backendWork "petrelhacker-backend"
foreach ($target in @($backendOutput, $backendWorkOutput)) {
    if ((Test-Path -LiteralPath $target) -and ((Resolve-Path -LiteralPath $target).Path.StartsWith((Resolve-Path -LiteralPath $buildRoot).Path))) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

Push-Location $root
try {
    & $pythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --name petrelhacker-backend `
        --distpath $backendDist `
        --workpath $backendWork `
        --specpath $specPath `
        --exclude-module PySide6 `
        --exclude-module matplotlib `
        --exclude-module scipy `
        --exclude-module numba `
        --exclude-module IPython `
        --exclude-module jedi `
        --exclude-module PIL `
        --exclude-module tkinter `
        --exclude-module zmq `
        --exclude-module pytest `
        web_backend\cli.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$backendExe = Join-Path $backendDist "petrelhacker-backend\petrelhacker-backend.exe"
if (-not (Test-Path -LiteralPath $backendExe)) {
    throw "Backend exe was not created: $backendExe"
}

Write-Host "Backend exe: $backendExe"
