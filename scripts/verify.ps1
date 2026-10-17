param(
    [switch]$SkipSmoke,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontendRoot = Join-Path $repoRoot "src/frontend"
$wheelDir = Join-Path $repoRoot ".build-verify"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host "==> $Name"
    & $Command
}

Push-Location $repoRoot
try {
    Invoke-Step "Python compile check" {
        $env:PYTHONPATH = "src/backend"
        python -m compileall -q src/backend tests
    }

    Invoke-Step "Backend unit tests" {
        $env:PYTHONPATH = "src/backend"
        python -m unittest discover -s tests -v
    }

    Invoke-Step "Python dependency check" {
        python -m pip check
    }

    Invoke-Step "Backend wheel build" {
        if (Test-Path -LiteralPath $wheelDir) {
            Remove-Item -LiteralPath $wheelDir -Recurse -Force
        }
        python -m pip wheel . -w $wheelDir
    }

    Invoke-Step "Frontend dependency install" {
        Push-Location $frontendRoot
        try {
            npm ci
        } finally {
            Pop-Location
        }
    }

    Invoke-Step "Frontend production build" {
        Push-Location $frontendRoot
        try {
            npm run build
        } finally {
            Pop-Location
        }
    }

    if (-not $SkipSmoke) {
        Invoke-Step "Frontend/backend smoke" {
            & (Join-Path $PSScriptRoot "frontend-smoke.ps1")
        }
    }
} finally {
    if (-not $KeepArtifacts) {
        $artifactPaths = @(
            (Join-Path $repoRoot ".build-verify"),
            (Join-Path $repoRoot "build"),
            (Join-Path $repoRoot "src/backend/software_cup_a3_backend.egg-info"),
            (Join-Path $frontendRoot "dist"),
            (Join-Path $frontendRoot "node_modules"),
            (Join-Path $frontendRoot "test-results"),
            (Join-Path $frontendRoot "playwright-report")
        )
        foreach ($path in $artifactPaths) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Recurse -Force
            }
        }
        Get-ChildItem -Path $repoRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
    }
    Pop-Location
}

Write-Host "Verification completed."
