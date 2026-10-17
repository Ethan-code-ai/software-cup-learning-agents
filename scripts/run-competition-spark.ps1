param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 5174,
    [string]$DatabaseUrl = "sqlite:///./data/demo.sqlite3",
    [string]$Model = "xop3qwen1b7",
    [int]$TimeoutSeconds = 45,
    [int]$MaxRetries = 1,
    [switch]$BypassProxy,
    [switch]$SmokeOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$apiKey = $env:XFYUN_SPARK_API_KEY
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $apiKey = [Environment]::GetEnvironmentVariable("XFYUN_SPARK_API_KEY", "User")
}
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "Missing XFYUN_SPARK_API_KEY. Set it once with: [Environment]::SetEnvironmentVariable('XFYUN_SPARK_API_KEY', '<your-spark-api-key>', 'User')"
}

$managedVariables = @(
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "LLM_MAX_TOKENS",
    "LLM_PLANNER_TIMEOUT_SECONDS",
    "LLM_PLANNER_MAX_RETRIES",
    "LLM_PLANNER_MAX_TOKENS",
    "LLM_PROFILE_UPDATER_TIMEOUT_SECONDS",
    "LLM_PROFILE_UPDATER_MAX_RETRIES",
    "LLM_PROFILE_UPDATER_MAX_TOKENS",
    "LLM_PROFILE_BUILDER_TIMEOUT_SECONDS",
    "LLM_PROFILE_BUILDER_MAX_RETRIES",
    "LLM_PROFILE_BUILDER_MAX_TOKENS",
    "LLM_EVALUATOR_TIMEOUT_SECONDS",
    "LLM_EVALUATOR_MAX_RETRIES",
    "LLM_EVALUATOR_MAX_TOKENS",
    "LLM_TUTOR_TIMEOUT_SECONDS",
    "LLM_TUTOR_MAX_RETRIES",
    "LLM_TUTOR_MAX_TOKENS",
    "LLM_QUIZ_TIMEOUT_SECONDS",
    "LLM_QUIZ_MAX_RETRIES",
    "LLM_QUIZ_MAX_TOKENS",
    "LLM_RESOURCE_TIMEOUT_SECONDS",
    "LLM_RESOURCE_MAX_RETRIES",
    "LLM_RESOURCE_MAX_TOKENS",
    "LLM_FALLBACK_MODE",
    "LLM_BYPASS_PROXY",
    "LLM_ENABLE_FOR_TUTOR",
    "LLM_ENABLE_FOR_RESOURCE",
    "LLM_ENABLE_FOR_EVALUATOR",
    "LLM_ENABLE_FOR_PROFILE_UPDATER",
    "LLM_ENABLE_FOR_PROFILE_BUILDER",
    "LLM_ENABLE_FOR_PLANNER",
    "LLM_ENABLE_FOR_QUIZ"
)
$previousValues = @{}
foreach ($name in $managedVariables) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:LLM_PROVIDER = "openai_compatible"
    $env:LLM_BASE_URL = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
    $env:LLM_API_KEY = $apiKey
    $env:LLM_MODEL = $Model
    $env:LLM_TIMEOUT_SECONDS = [string]$TimeoutSeconds
    $env:LLM_MAX_RETRIES = [string]$MaxRetries
    $env:LLM_MAX_TOKENS = "1024"
    $env:LLM_PLANNER_TIMEOUT_SECONDS = "18"
    $env:LLM_PLANNER_MAX_RETRIES = "0"
    $env:LLM_PLANNER_MAX_TOKENS = "600"
    $env:LLM_PROFILE_UPDATER_TIMEOUT_SECONDS = "12"
    $env:LLM_PROFILE_UPDATER_MAX_RETRIES = "0"
    $env:LLM_PROFILE_UPDATER_MAX_TOKENS = "700"
    $env:LLM_PROFILE_BUILDER_TIMEOUT_SECONDS = "15"
    $env:LLM_PROFILE_BUILDER_MAX_RETRIES = "0"
    $env:LLM_PROFILE_BUILDER_MAX_TOKENS = "900"
    $env:LLM_EVALUATOR_TIMEOUT_SECONDS = "15"
    $env:LLM_EVALUATOR_MAX_RETRIES = "0"
    $env:LLM_EVALUATOR_MAX_TOKENS = "900"
    $env:LLM_TUTOR_TIMEOUT_SECONDS = "25"
    $env:LLM_TUTOR_MAX_RETRIES = "0"
    $env:LLM_TUTOR_MAX_TOKENS = "800"
    $env:LLM_QUIZ_TIMEOUT_SECONDS = "20"
    $env:LLM_QUIZ_MAX_RETRIES = "0"
    $env:LLM_QUIZ_MAX_TOKENS = "1400"
    $env:LLM_RESOURCE_TIMEOUT_SECONDS = "30"
    $env:LLM_RESOURCE_MAX_RETRIES = "0"
    $env:LLM_RESOURCE_MAX_TOKENS = "1200"
    $env:LLM_FALLBACK_MODE = "rule_based"
    $env:LLM_BYPASS_PROXY = if ($BypassProxy) { "true" } else { "false" }
    $env:LLM_ENABLE_FOR_TUTOR = "true"
    $env:LLM_ENABLE_FOR_RESOURCE = "true"
    $env:LLM_ENABLE_FOR_EVALUATOR = "true"
    $env:LLM_ENABLE_FOR_PROFILE_UPDATER = "true"
    $env:LLM_ENABLE_FOR_PROFILE_BUILDER = "true"
    $env:LLM_ENABLE_FOR_PLANNER = "true"
    $env:LLM_ENABLE_FOR_QUIZ = "true"

    $scriptArgs = @{
        BackendHost = $BackendHost
        BackendPort = $BackendPort
        FrontendHost = $FrontendHost
        FrontendPort = $FrontendPort
        DatabaseUrl = $DatabaseUrl
        UseRemoteTutorLLM = $true
        AutoSelectFrontendPort = $true
    }
    if ($SmokeOnly) {
        $scriptArgs["SmokeOnly"] = $true
    }

    & (Join-Path $repoRoot "scripts/run-local.ps1") @scriptArgs
} finally {
    foreach ($name in $managedVariables) {
        $previousValue = $previousValues[$name]
        if ($null -eq $previousValue) {
            Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $previousValue, "Process")
        }
    }
}
