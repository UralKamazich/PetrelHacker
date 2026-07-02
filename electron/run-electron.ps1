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

$env:ELECTRON_RUN_AS_NODE = $null
& $nodeExe (Join-Path $PSScriptRoot "launch.js")
exit $LASTEXITCODE
