param(
    [string]$EnvFile = "hatchery/.env",
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 8090,
    [switch]$WithBridge,
    [string]$BridgeHost = "127.0.0.1",
    [int]$BridgePort = 8190
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    if (Test-Path $StdoutPath) { Remove-Item -Force $StdoutPath }
    if (Test-Path $StderrPath) { Remove-Item -Force $StderrPath }

    $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $RepoRoot -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath -PassThru
    Write-Host "[STARTED] $Name PID=$($proc.Id)" -ForegroundColor Green
    return $proc
}

$workspace = Join-Path $RepoRoot "workspace\hatchery"
New-Item -ItemType Directory -Force -Path $workspace | Out-Null

$apiOut = Join-Path $workspace "service.stdout.log"
$apiErr = Join-Path $workspace "service.stderr.log"
$bridgeOut = Join-Path $workspace "bridge.stdout.log"
$bridgeErr = Join-Path $workspace "bridge.stderr.log"

$resolvedEnvFile = Join-Path $RepoRoot $EnvFile
if (-not (Test-Path $resolvedEnvFile)) {
    $envDir = Split-Path -Parent $resolvedEnvFile
    if ($envDir) {
        New-Item -ItemType Directory -Force -Path $envDir | Out-Null
    }
    $exampleFile = Join-Path $envDir ".env.example"
    if (-not (Test-Path $exampleFile)) {
        throw "Env file not found: $resolvedEnvFile ; example template also missing: $exampleFile"
    }
    Copy-Item -Path $exampleFile -Destination $resolvedEnvFile
    Write-Host "[BOOTSTRAP] Created env file from template: $resolvedEnvFile" -ForegroundColor Yellow
}

$env:HATCHERY_ENV_FILE = $resolvedEnvFile
$api = Start-ManagedProcess -Name "hatchery-service" -FilePath "python" -ArgumentList @("-m", "hatchery.service_runner", "--host", $ApiHost, "--port", "$ApiPort") -StdoutPath $apiOut -StderrPath $apiErr

if ($WithBridge) {
    $bridge = Start-ManagedProcess -Name "hatchery-bridge" -FilePath "python" -ArgumentList @("-m", "hatchery.orchestrator_bridge.runner", "--service-url", "http://$ApiHost`:$ApiPort", "--host", $BridgeHost, "--port", "$BridgePort") -StdoutPath $bridgeOut -StderrPath $bridgeErr
}

Write-Host ""
Write-Host "API GUI:     http://$ApiHost`:$ApiPort/gui" -ForegroundColor Cyan
Write-Host "API Docs:    http://$ApiHost`:$ApiPort/docs" -ForegroundColor Cyan
if ($WithBridge) {
    Write-Host "Bridge Docs: http://$BridgeHost`:$BridgePort/docs" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Logs:" -ForegroundColor Yellow
Write-Host "  $apiOut"
Write-Host "  $apiErr"
if ($WithBridge) {
    Write-Host "  $bridgeOut"
    Write-Host "  $bridgeErr"
}
