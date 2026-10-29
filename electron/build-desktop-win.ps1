$ErrorActionPreference = "Stop"

$root = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")

function Resolve-NodeExe {
    $candidates = @()
    if ($env:PETRELHACKER_NODE) {
        $candidates += $env:PETRELHACKER_NODE
    }

    $toolsPath = Join-Path $root ".tools"
    $nodeRoot = Get-ChildItem -LiteralPath $toolsPath -Directory -Filter "node-*-win-x64" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($nodeRoot) {
        $candidates += (Join-Path $nodeRoot.FullName "node.exe")
    }

    $commandNode = Get-Command node -ErrorAction SilentlyContinue
    if ($commandNode) {
        $candidates += $commandNode.Source
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Node.js was not found. Install Node.js, place portable Node in .tools\node-*-win-x64, or set PETRELHACKER_NODE."
}

function Resolve-NpmExe($nodeExe) {
    $nodeDir = Split-Path -Parent $nodeExe
    $localNpm = Join-Path $nodeDir "npm.cmd"
    if (Test-Path -LiteralPath $localNpm) {
        return $localNpm
    }

    $commandNpm = Get-Command npm -ErrorAction SilentlyContinue
    if ($commandNpm) {
        return $commandNpm.Source
    }

    return $null
}

$nodeExe = Resolve-NodeExe
$nodeDir = Split-Path -Parent $nodeExe
$env:PATH = "$nodeDir;$env:PATH"

$builderCli = Join-Path $root "node_modules\electron-builder\out\cli\cli.js"
if (-not (Test-Path -LiteralPath $builderCli)) {
    $npmExe = Resolve-NpmExe $nodeExe
    if (-not $npmExe) {
        throw "npm was not found and node_modules are missing. Run npm install, or use Node.js with npm available."
    }

    Push-Location $root
    try {
        if (Test-Path -LiteralPath (Join-Path $root "package-lock.json")) {
            & $npmExe ci
        }
        else {
            & $npmExe install
        }
        if ($LASTEXITCODE -ne 0) {
            throw "npm dependency install failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

& (Join-Path $PSScriptRoot "build-backend.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Backend build failed with exit code $LASTEXITCODE"
}

Push-Location $root
try {
    & $nodeExe $builderCli --win portable --x64 --publish never
    if ($LASTEXITCODE -ne 0) {
        throw "electron-builder failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$artifact = Get-ChildItem -LiteralPath (Join-Path $root "dist-electron-web") -Filter "PetrelHacker-*-portable.exe" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $artifact) {
    throw "Standalone desktop exe was not created in dist-electron-web."
}

Write-Host "Standalone desktop exe: $($artifact.FullName)"
