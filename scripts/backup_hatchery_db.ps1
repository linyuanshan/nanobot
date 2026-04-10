param(
    [string]$DatabasePath = "workspace/hatchery/hatchery.db",
    [string]$BackupDir = "workspace/hatchery/backups"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$db = Join-Path $RepoRoot $DatabasePath
if (-not (Test-Path $db)) {
    throw "Database not found: $db"
}

$targetDir = Join-Path $RepoRoot $BackupDir
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dest = Join-Path $targetDir "hatchery-$stamp.db"
Copy-Item -Force $db $dest

foreach ($suffix in @("-wal", "-shm")) {
    $sidecar = "$db$suffix"
    if (Test-Path $sidecar) {
        Copy-Item -Force $sidecar "$dest$suffix"
    }
}

Write-Host "Backup created: $dest" -ForegroundColor Green