$ErrorActionPreference = "Stop"

$root = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$nodeRoot = Get-ChildItem -LiteralPath (Join-Path $root ".tools") -Directory -Filter "node-*-win-x64" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    Select-Object -First 1

if (-not $nodeRoot) {
    throw "Portable Node was not found in .tools. Download Node or run the setup step again."
}

$nodeExe = Join-Path $nodeRoot.FullName "node.exe"
if (-not (Test-Path -LiteralPath $nodeExe)) {
    throw "node.exe was not found: $nodeExe"
}

$env:PATH = "$($nodeRoot.FullName);$env:PATH"

& (Join-Path $PSScriptRoot "build-backend.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Backend build failed with exit code $LASTEXITCODE"
}

Push-Location $root
try {
    & $nodeExe node_modules\electron-builder\out\cli\cli.js --win portable --x64 --publish never
    if ($LASTEXITCODE -ne 0) {
        throw "electron-builder failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
