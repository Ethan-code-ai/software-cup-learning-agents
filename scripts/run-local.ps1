param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 5173,
    [string]$DatabaseUrl = "sqlite:///./data/demo.sqlite3",
    [string]$PythonExecutable = "python",
    [switch]$SkipFrontendInstall,
    [switch]$SkipDemoLoad,
    [switch]$UseRemoteTutorLLM,
    [switch]$AutoSelectFrontendPort,
    [switch]$SmokeOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontendRoot = Join-Path $repoRoot "src/frontend"
$viteEntry = Join-Path $frontendRoot "node_modules/vite/bin/vite.js"
$backendOut = Join-Path $env:TEMP "software-cup-a3-local-backend.out.log"
$backendErr = Join-Path $env:TEMP "software-cup-a3-local-backend.err.log"
$frontendOut = Join-Path $env:TEMP "software-cup-a3-local-frontend.out.log"
$frontendErr = Join-Path $env:TEMP "software-cup-a3-local-frontend.err.log"

function Assert-PortFree {
    param([int]$Port)

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "Port $Port is already in use by process id(s): $owners"
    }
}

function Find-AvailableTcpPort {
    param(
        [int]$StartPort,
        [int]$MaxAttempts = 100
    )

    for ($offset = 0; $offset -lt $MaxAttempts; $offset++) {
        $candidate = $StartPort + $offset
        if ($candidate -gt 65535) {
            break
        }
        $listeners = Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue
        if (-not $listeners) {
            return $candidate
        }
    }
    throw "No available frontend port found from $StartPort within $MaxAttempts attempts."
}

function Wait-ForHttp {
    param(
        [string]$Uri,
        [int]$Attempts = 40
    )

    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            return Invoke-WebRequest -Uri $Uri -UseBasicParsing
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timed out waiting for $Uri"
}

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Uri
    )

    Invoke-RestMethod -Method $Method -Uri $Uri -ContentType "application/json"
}

function Stop-OwnedProcess {
    param([System.Diagnostics.Process]$Process)

    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(5000) | Out-Null
    }
}

if ($AutoSelectFrontendPort) {
    $requestedFrontendPort = $FrontendPort
    $FrontendPort = Find-AvailableTcpPort -StartPort $requestedFrontendPort
    if ($FrontendPort -ne $requestedFrontendPort) {
        Write-Host "Frontend port $requestedFrontendPort is occupied; using available port $FrontendPort instead."
    }
}

Assert-PortFree -Port $BackendPort
Assert-PortFree -Port $FrontendPort

if (-not $SkipFrontendInstall -and -not (Test-Path -LiteralPath $viteEntry)) {
    Push-Location $frontendRoot
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $viteEntry)) {
    throw "Frontend dependencies are missing. Run npm ci in $frontendRoot before starting the local demo."
}

New-Item -ItemType Directory -Force -Path (Join-Path $repoRoot "data") | Out-Null
Remove-Item -LiteralPath $backendOut,$backendErr,$frontendOut,$frontendErr -Force -ErrorAction SilentlyContinue

$oldPythonPath = $env:PYTHONPATH
$oldDatabaseUrl = $env:APP_DATABASE_URL
$oldViteBase = $env:VITE_API_BASE_URL
$oldViteProxyTarget = $env:VITE_PROXY_TARGET
$oldLlmProvider = $env:LLM_PROVIDER
$oldLlmTutorEnabled = $env:LLM_ENABLE_FOR_TUTOR
$oldLlmResourceEnabled = $env:LLM_ENABLE_FOR_RESOURCE
$oldLlmEvaluatorEnabled = $env:LLM_ENABLE_FOR_EVALUATOR
$oldLlmProfileUpdaterEnabled = $env:LLM_ENABLE_FOR_PROFILE_UPDATER

$backend = $null
$frontend = $null
$backendBase = "http://$BackendHost`:$BackendPort"
$frontendBase = "http://$FrontendHost`:$FrontendPort"

try {
    $env:PYTHONPATH = "src/backend"
    $env:APP_DATABASE_URL = $DatabaseUrl
    if (-not $UseRemoteTutorLLM) {
        $env:LLM_PROVIDER = "rule_based"
        $env:LLM_ENABLE_FOR_TUTOR = "false"
        $env:LLM_ENABLE_FOR_RESOURCE = "false"
        $env:LLM_ENABLE_FOR_EVALUATOR = "false"
        $env:LLM_ENABLE_FOR_PROFILE_UPDATER = "false"
    }

    $backend = Start-Process -FilePath $PythonExecutable `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $BackendHost, "--port", [string]$BackendPort) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr `
        -PassThru

    Wait-ForHttp -Uri "$backendBase/api/v1/demo-data/status" | Out-Null

    if (-not $SkipDemoLoad) {
        Invoke-Json -Method "POST" -Uri "$backendBase/api/v1/demo-data/load" | Out-Null
    }

    $env:VITE_API_BASE_URL = "/api/v1"
    $env:VITE_PROXY_TARGET = $backendBase

    $frontend = Start-Process -FilePath "node" `
        -ArgumentList @($viteEntry, "--host", $FrontendHost, "--port", [string]$FrontendPort, "--strictPort") `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr `
        -PassThru

    $frontendPage = Wait-ForHttp -Uri "$frontendBase/"
    if (-not $frontendPage.Content.Contains('id="root"')) {
        throw "Frontend page did not contain React root."
    }

    [pscustomobject]@{
        BackendUrl = $backendBase
        FrontendUrl = $frontendBase
        DatabaseUrl = $DatabaseUrl
        DemoDataLoaded = (-not $SkipDemoLoad)
        RemoteTutorLLM = [bool]$UseRemoteTutorLLM
        BackendLog = $backendOut
        FrontendLog = $frontendOut
    } | Format-List

    if ($SmokeOnly) {
        return
    }

    Write-Host "Local demo is running. Press Ctrl+C to stop backend and frontend."
    while ($true) {
        if ($backend.HasExited) {
            throw "Backend process exited. See $backendErr"
        }
        if ($frontend.HasExited) {
            throw "Frontend process exited. See $frontendErr"
        }
        Start-Sleep -Seconds 1
    }
} finally {
    Stop-OwnedProcess -Process $frontend
    Stop-OwnedProcess -Process $backend

    if ($null -eq $oldPythonPath) { Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
    if ($null -eq $oldDatabaseUrl) { Remove-Item Env:\APP_DATABASE_URL -ErrorAction SilentlyContinue } else { $env:APP_DATABASE_URL = $oldDatabaseUrl }
    if ($null -eq $oldViteBase) { Remove-Item Env:\VITE_API_BASE_URL -ErrorAction SilentlyContinue } else { $env:VITE_API_BASE_URL = $oldViteBase }
    if ($null -eq $oldViteProxyTarget) { Remove-Item Env:\VITE_PROXY_TARGET -ErrorAction SilentlyContinue } else { $env:VITE_PROXY_TARGET = $oldViteProxyTarget }
    if ($null -eq $oldLlmProvider) { Remove-Item Env:\LLM_PROVIDER -ErrorAction SilentlyContinue } else { $env:LLM_PROVIDER = $oldLlmProvider }
    if ($null -eq $oldLlmTutorEnabled) { Remove-Item Env:\LLM_ENABLE_FOR_TUTOR -ErrorAction SilentlyContinue } else { $env:LLM_ENABLE_FOR_TUTOR = $oldLlmTutorEnabled }
    if ($null -eq $oldLlmResourceEnabled) { Remove-Item Env:\LLM_ENABLE_FOR_RESOURCE -ErrorAction SilentlyContinue } else { $env:LLM_ENABLE_FOR_RESOURCE = $oldLlmResourceEnabled }
    if ($null -eq $oldLlmEvaluatorEnabled) { Remove-Item Env:\LLM_ENABLE_FOR_EVALUATOR -ErrorAction SilentlyContinue } else { $env:LLM_ENABLE_FOR_EVALUATOR = $oldLlmEvaluatorEnabled }
    if ($null -eq $oldLlmProfileUpdaterEnabled) { Remove-Item Env:\LLM_ENABLE_FOR_PROFILE_UPDATER -ErrorAction SilentlyContinue } else { $env:LLM_ENABLE_FOR_PROFILE_UPDATER = $oldLlmProfileUpdaterEnabled }
}
