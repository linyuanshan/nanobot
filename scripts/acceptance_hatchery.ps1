param(
    [string]$BaseUrl = "http://127.0.0.1:8090",
    [int]$Port = 8090,
    [switch]$SkipServerStart,
    [switch]$SkipTimeoutCase,
    [switch]$KeepServer
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DbPath = Join-Path $RepoRoot "workspace\hatchery\hatchery.db"
$StdoutLog = Join-Path $RepoRoot "workspace\hatchery\acceptance-uvicorn.stdout.log"
$StderrLog = Join-Path $RepoRoot "workspace\hatchery\acceptance-uvicorn.stderr.log"
$ServerProcess = $null

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw "ASSERT FAILED: $Message"
    }
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Assert-Equal {
    param(
        $Actual,
        $Expected,
        [string]$Message
    )
    if ($Actual -ne $Expected) {
        throw "ASSERT FAILED: $Message`nExpected: $Expected`nActual:   $Actual"
    }
    Write-Host "[PASS] $Message -> $Actual" -ForegroundColor Green
}

function Get-BodyField {
    param(
        $Body,
        [string]$Name
    )

    if ($null -eq $Body) {
        return $null
    }
    if ($Body -is [System.Collections.IDictionary]) {
        return $Body[$Name]
    }
    $property = $Body.PSObject.Properties[$Name]
    if ($null -ne $property) {
        return $property.Value
    }
    return $null
}

function Invoke-Json {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Url,
        $Body = $null
    )

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Url
    }

    $json = $Body | ConvertTo-Json -Depth 10
    return Invoke-RestMethod -Method $Method -Uri $Url -ContentType "application/json" -Body $json
}

function Get-HttpStatusAndBody {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Url,
        $Body = $null
    )

    try {
        if ($null -eq $Body) {
            $response = Invoke-WebRequest -Method $Method -Uri $Url -UseBasicParsing
        } else {
            $json = $Body | ConvertTo-Json -Depth 10
            $response = Invoke-WebRequest -Method $Method -Uri $Url -UseBasicParsing -ContentType "application/json" -Body $json
        }
        return @{
            StatusCode = [int]$response.StatusCode
            Body = if ($response.Content) { $response.Content | ConvertFrom-Json } else { $null }
            BodyText = $response.Content
        }
    } catch {
        $httpResponse = $_.Exception.Response
        if ($null -eq $httpResponse) {
            throw
        }
        $reader = New-Object System.IO.StreamReader($httpResponse.GetResponseStream())
        $content = $reader.ReadToEnd()
        $reader.Close()
        return @{
            StatusCode = [int]$httpResponse.StatusCode
            Body = if ($content) { $content | ConvertFrom-Json } else { $null }
            BodyText = $content
        }
    }
}

function Wait-ForServer {
    param([string]$DocsUrl)

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $DocsUrl -UseBasicParsing -TimeoutSec 2
            if ([int]$response.StatusCode -eq 200) {
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Timed out waiting for hatchery service at $DocsUrl"
}

function Wait-ForCommandStatus {
    param(
        [string]$CommandId,
        [string]$ExpectedStatus,
        [int]$TimeoutSec = 220
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $command = Invoke-Json -Method GET -Url "$BaseUrl/api/v1/commands/$CommandId"
        if ($command.status -eq $ExpectedStatus) {
            return $command
        }
        Start-Sleep -Seconds 5
    }
    throw "Timed out waiting for command $CommandId to reach status $ExpectedStatus"
}

function Stop-PortProcess {
    param([int]$LocalPort)

    $listeners = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($listenerPid in $listeners) {
        if ($listenerPid) {
            Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
    }
}

function Start-HatcheryServer {
    Write-Step "Starting hatchery API"

    python -c "import fastapi, uvicorn" | Out-Null
    Stop-PortProcess -LocalPort $Port

    if (Test-Path $DbPath) {
        try {
            Remove-Item -Force $DbPath
        } catch {
            Write-Host "[WARN] could not delete existing DB, continuing with current file" -ForegroundColor Yellow
        }
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DbPath) | Out-Null
    if (Test-Path $StdoutLog) {
        Remove-Item -Force $StdoutLog
    }
    if (Test-Path $StderrLog) {
        Remove-Item -Force $StderrLog
    }

    $script:ServerProcess = Start-Process `
        -FilePath "python" `
        -ArgumentList @("-m", "uvicorn", "hatchery.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru

    Wait-ForServer -DocsUrl "$BaseUrl/docs"
    Write-Host "[PASS] hatchery service is reachable at $BaseUrl" -ForegroundColor Green
}

function Stop-HatcheryServer {
    if ($null -ne $script:ServerProcess -and -not $script:ServerProcess.HasExited) {
        Stop-Process -Id $script:ServerProcess.Id -Force
        Write-Host "[INFO] stopped hatchery server PID $($script:ServerProcess.Id)" -ForegroundColor Yellow
    }
}

try {
    if (-not $SkipServerStart) {
        Start-HatcheryServer
    }

    Write-Step "Health and readiness probes"
    $health = Invoke-Json -Method GET -Url "$BaseUrl/healthz"
    Assert-Equal $health.status "ok" "healthz reports ok"
    $ready = Get-HttpStatusAndBody -Method GET -Url "$BaseUrl/readyz"
    Assert-Equal $ready.StatusCode 200 "readyz returns 200"
    Assert-Equal (Get-BodyField -Body $ready.Body -Name "status") "ready" "readyz reports ready"

    Write-Step "Water-quality ingest and danger assessment"
    $telemetryDanger = @{
        site_id = "site-001"
        workshop_id = "ws-001"
        pool_id = "pool-01"
        mode = "sim"
        ts = "2026-02-07T10:00:00Z"
        payload = @{
            relay = 0
            ph = 7.42
            hzd = 3
            rjy = 2.95
            temp = 24.7
        }
    }
    $telemetryResponse = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/telemetry/water-quality" -Body $telemetryDanger
    Assert-Equal $telemetryResponse.StatusCode 202 "telemetry ingest returns 202"
    Assert-Equal (Get-BodyField -Body $telemetryResponse.Body -Name "event_type") "telemetry.water_quality.v1" "telemetry event type is normalized"
    Assert-Equal (Get-BodyField -Body (Get-BodyField -Body $telemetryResponse.Body -Name "payload") -Name "do_mg_l") 2.95 "rjy maps to do_mg_l"
    $pool01 = Invoke-Json -Method GET -Url "$BaseUrl/api/v1/pools/pool-01/state"
    Assert-Equal $pool01.assessment.level "danger" "pool-01 is assessed as danger"

    Write-Step "Bio perception and action plan"
    $telemetryNormal = @{
        site_id = "site-001"
        workshop_id = "ws-001"
        pool_id = "pool-02"
        mode = "sim"
        ts = "2026-02-07T10:01:00Z"
        payload = @{
            relay = 0
            ph = 7.9
            hzd = 3
            rjy = 6.10
            temp = 24.5
        }
    }
    Invoke-Json -Method POST -Url "$BaseUrl/api/v1/telemetry/water-quality" -Body $telemetryNormal | Out-Null
    $bio = @{
        site_id = "site-001"
        workshop_id = "ws-001"
        pool_id = "pool-02"
        mode = "sim"
        ts = "2026-02-07T10:02:00Z"
        payload = @{
            count = 120
            size_distribution = @("small", "medium")
            activity_score = 0.65
            hunger_score = 0.85
            confidence = 0.98
            model_version = "replay-v1"
        }
    }
    $bioResponse = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/perception/bio" -Body $bio
    Assert-Equal $bioResponse.StatusCode 202 "bio ingest returns 202"
    $plan = Invoke-Json -Method POST -Url "$BaseUrl/api/v1/decisions/plan" -Body @{
        pool_id = "pool-02"
        trace_id = "trace-plan-001"
        model_version = "policy-v1"
    }
    Assert-Equal $plan.actions[0].action_type "feed" "action plan proposes feed for hungry pool"

    Write-Step "Low-risk command executes immediately"
    $lowRiskCommand = @{
        command_id = "cmd-lowrisk-001"
        idempotency_key = "pool-02-feed-202602071100"
        trace_id = "trace-lowrisk-001"
        mode = "sim"
        action_type = "feed"
        target = @{
            site_id = "site-001"
            workshop_id = "ws-001"
            pool_id = "pool-02"
        }
        params = @{
            ratio = 0.60
            duration_sec = 120
        }
        preconditions = @{
            min_do_mg_l = 5.0
            max_temp_c = 29.0
        }
        deadline_sec = 180
        degrade_policy = "feed_60_percent_on_timeout"
        dry_run = $true
    }
    $lowRiskResponse = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/commands" -Body $lowRiskCommand
    Assert-Equal $lowRiskResponse.StatusCode 200 "low-risk command returns 200"
    Assert-Equal (Get-BodyField -Body $lowRiskResponse.Body -Name "status") "Closed" "low-risk command closes immediately"
    Assert-Equal (Get-BodyField -Body $lowRiskResponse.Body -Name "result_code") "OK" "low-risk command result code is OK"

    Write-Step "Duplicate idempotency is rejected"
    $duplicateResponse = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/commands" -Body @{
        command_id = "cmd-lowrisk-002"
        idempotency_key = "pool-02-feed-202602071100"
        trace_id = "trace-lowrisk-002"
        mode = "sim"
        action_type = "feed"
        target = @{
            site_id = "site-001"
            workshop_id = "ws-001"
            pool_id = "pool-02"
        }
        params = @{
            ratio = 0.60
            duration_sec = 120
        }
        preconditions = @{
            min_do_mg_l = 5.0
            max_temp_c = 29.0
        }
        deadline_sec = 180
        degrade_policy = "feed_60_percent_on_timeout"
        dry_run = $true
    }
    Assert-Equal $duplicateResponse.StatusCode 409 "duplicate idempotency returns 409"

    Write-Step "High-risk approval confirm flow"
    $approveCommand = @{
        command_id = "cmd-approve-001"
        idempotency_key = "pool-03-water-change-202602071200"
        trace_id = "trace-approve-001"
        mode = "shadow"
        action_type = "water_change"
        target = @{
            site_id = "site-001"
            workshop_id = "ws-001"
            pool_id = "pool-03"
        }
        params = @{
            ratio = 0.30
            duration_sec = 180
        }
        preconditions = @{
            min_do_mg_l = 5.0
            max_temp_c = 29.0
        }
        deadline_sec = 180
        degrade_policy = "aerate_up_on_timeout"
        dry_run = $true
    }
    $approveResponse = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/commands" -Body $approveCommand
    Assert-Equal $approveResponse.StatusCode 202 "high-risk command returns 202"
    Assert-Equal (Get-BodyField -Body $approveResponse.Body -Name "status") "PendingApproval" "high-risk command waits for approval"
    $approvalId = [string](Get-BodyField -Body $approveResponse.Body -Name "approval_id")
    Assert-True ($approvalId.Length -gt 0) "approval id is present"
    $approvalLookup = Invoke-Json -Method POST -Url "$BaseUrl/api/v1/approvals/requests" -Body @{
        command_id = "cmd-approve-001"
        timeout_sec = 180
        remind_at_sec = 120
        provider = "local"
    }
    Assert-Equal $approvalLookup.approval_id $approvalId "approval lookup returns the same approval id"
    $confirmResponse = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/approvals/$approvalId/confirm" -Body @{
        operator = "owner-001"
        reason = "manual acceptance"
    }
    Assert-Equal $confirmResponse.StatusCode 200 "approval confirm returns 200"
    Assert-Equal (Get-BodyField -Body $confirmResponse.Body -Name "status") "Closed" "confirmed command reaches closed state"
    Assert-Equal (Get-BodyField -Body $confirmResponse.Body -Name "effective_action_type") "water_change" "confirmed command keeps original action"
    Assert-Equal (Get-BodyField -Body (Get-BodyField -Body $confirmResponse.Body -Name "receipt") -Name "adapter") "shadow-relay-adapter-v1" "shadow adapter is used for shadow mode"

    Write-Step "High-risk approval reject flow"
    $rejectCommand = @{
        command_id = "cmd-reject-001"
        idempotency_key = "pool-04-water-change-202602071201"
        trace_id = "trace-reject-001"
        mode = "sim"
        action_type = "water_change"
        target = @{
            site_id = "site-001"
            workshop_id = "ws-001"
            pool_id = "pool-04"
        }
        params = @{
            ratio = 0.30
            duration_sec = 180
        }
        preconditions = @{
            min_do_mg_l = 5.0
            max_temp_c = 29.0
        }
        deadline_sec = 180
        degrade_policy = "aerate_up_on_timeout"
        dry_run = $true
    }
    $rejectSubmit = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/commands" -Body $rejectCommand
    Assert-Equal $rejectSubmit.StatusCode 202 "reject-case command returns 202"
    $rejectApprovalId = [string](Get-BodyField -Body $rejectSubmit.Body -Name "approval_id")
    $rejectResponse = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/approvals/$rejectApprovalId/reject" -Body @{
        operator = "owner-002"
        reason = "manual reject"
    }
    Assert-Equal $rejectResponse.StatusCode 200 "approval reject returns 200"
    Assert-Equal (Get-BodyField -Body $rejectResponse.Body -Name "status") "Closed" "rejected command reaches closed state"
    Assert-Equal (Get-BodyField -Body $rejectResponse.Body -Name "result_code") "E_RISK_NOT_APPROVED" "rejected command returns not-approved result"

    if (-not $SkipTimeoutCase) {
        Write-Step "High-risk timeout degrade flow (this waits a little over 3 minutes)"
        $timeoutCommand = @{
            command_id = "cmd-timeout-001"
            idempotency_key = "pool-05-water-change-202602071202"
            trace_id = "trace-timeout-001"
            mode = "sim"
            action_type = "water_change"
            target = @{
                site_id = "site-001"
                workshop_id = "ws-001"
                pool_id = "pool-05"
            }
            params = @{
                ratio = 0.30
                duration_sec = 180
            }
            preconditions = @{
                min_do_mg_l = 5.0
                max_temp_c = 29.0
            }
            deadline_sec = 180
            degrade_policy = "aerate_up_on_timeout"
            dry_run = $true
        }
        $timeoutSubmit = Get-HttpStatusAndBody -Method POST -Url "$BaseUrl/api/v1/commands" -Body $timeoutCommand
        Assert-Equal $timeoutSubmit.StatusCode 202 "timeout-case command returns 202"
        $timedOutCommand = Wait-ForCommandStatus -CommandId "cmd-timeout-001" -ExpectedStatus "Closed" -TimeoutSec 220
        Assert-Equal $timedOutCommand.effective_action_type "aerate_up" "timeout degrades water_change to aerate_up"
        Assert-Equal $timedOutCommand.result_code "OK" "timeout-degraded command still completes successfully"
        Assert-True ($timedOutCommand.transition_path -contains "TimedOut") "transition path includes TimedOut"
        Assert-True ($timedOutCommand.transition_path -contains "Degraded") "transition path includes Degraded"
        Assert-Equal $timedOutCommand.receipt.adapter "sim-relay-adapter-v1" "timeout-degraded sim command uses sim adapter"
    }

    Write-Step "Audit query"
    $allAudits = Invoke-Json -Method GET -Url "$BaseUrl/api/v1/audits"
    Assert-True ($allAudits.Count -ge 4) "audit list contains multiple records"
    $approveAudits = Invoke-Json -Method GET -Url "$BaseUrl/api/v1/audits?trace_id=trace-approve-001"
    Assert-True ($approveAudits.Count -ge 2) "trace-specific audit query returns records"

    Write-Host ""
    Write-Host "HATCHERY ACCEPTANCE PASSED" -ForegroundColor Green
    Write-Host "Base URL: $BaseUrl"
    Write-Host "DB Path:   $DbPath"
}
finally {
    if (-not $KeepServer) {
        Stop-HatcheryServer
    }
}



