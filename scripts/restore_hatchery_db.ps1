param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [string]$DatabasePath = "workspace/hatchery/hatchery.db"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$source = Resolve-Path $BackupFile
$db = Join-Path $RepoRoot $DatabasePath
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $db) | Out-Null
Copy-Item -Force $source $db

foreach ($suffix in @("-wal", "-shm")) {
    $sidecar = "$source$suffix"
    if (Test-Path $sidecar) {
        Copy-Item -Force $sidecar "$db$suffix"
    }
}

Write-Host "Database restored to: $db" -ForegroundColor Green