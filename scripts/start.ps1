[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendScript = Join-Path $Root "backend\run.py"
$FrontendDir = Join-Path $Root "frontend"
$RuntimeDir = Join-Path $Root ".run"
$PidFile = Join-Path $RuntimeDir "processes.json"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host "[START FAILED] $Message" -ForegroundColor Red
    exit 1
}

function Find-AiEnvironment {
    $candidates = @()
    if ($env:CONDA_PREFIX -and (Split-Path $env:CONDA_PREFIX -Leaf) -eq "ai") {
        $candidates += $env:CONDA_PREFIX
    }
    $candidates += @(
        (Join-Path $env:USERPROFILE ".conda\envs\ai"),
        (Join-Path $env:USERPROFILE "anaconda3\envs\ai"),
        (Join-Path $env:USERPROFILE "miniconda3\envs\ai"),
        "C:\ProgramData\anaconda3\envs\ai",
        "C:\ProgramData\miniconda3\envs\ai"
    )

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if ($candidate -and (Test-Path (Join-Path $candidate "python.exe"))) {
            return $candidate
        }
    }

    $conda = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($conda) {
        try {
            $environments = (& $conda.Source env list --json | ConvertFrom-Json).envs
            foreach ($environment in $environments) {
                if ((Split-Path $environment -Leaf) -eq "ai" -and
                    (Test-Path (Join-Path $environment "python.exe"))) {
                    return $environment
                }
            }
        }
        catch {
            return $null
        }
    }
    return $null
}

function Test-LocalPort {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(250)) {
            return $false
        }
        $client.EndConnect($connection)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Stop-ProcessTree {
    param([System.Diagnostics.Process]$Process)
    if (-not $Process) {
        return
    }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
        }
    }
    catch {
        # The process may already have exited.
    }
}

function Start-ChildProcess {
    param(
        [string]$FilePath,
        [string]$Arguments,
        [string]$WorkingDirectory
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = $Arguments
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    return [System.Diagnostics.Process]::Start($startInfo)
}

function Open-ApplicationPage {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "http://localhost:5173"
    $startInfo.UseShellExecute = $true
    [System.Diagnostics.Process]::Start($startInfo) | Out-Null
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " EnterpriseMind Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$EnvironmentRoot = Find-AiEnvironment
if (-not $EnvironmentRoot) {
    Stop-WithMessage "Conda environment 'ai' was not found."
}

$Python = Join-Path $EnvironmentRoot "python.exe"
$Node = Join-Path $EnvironmentRoot "node.exe"
if (-not (Test-Path $Node)) {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($nodeCommand) {
        $Node = $nodeCommand.Source
    }
}
$ViteScript = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"

if (-not (Test-Path $BackendScript)) {
    Stop-WithMessage "backend\run.py was not found."
}
if (-not (Test-Path $Node)) {
    Stop-WithMessage "Node.js was not found. Install Node.js in 'ai' or add node to PATH."
}
if (-not (Test-Path $ViteScript)) {
    Stop-WithMessage "Frontend dependencies are missing. Run npm install in frontend first."
}

Write-Host "[1/3] Checking Python dependencies..." -ForegroundColor Yellow
& $Python -c "import fastapi, sqlalchemy, alembic, langgraph, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Python dependencies are missing. Install backend\requirements.txt first."
}

Write-Host "[2/3] Environment ready: $EnvironmentRoot" -ForegroundColor Green
if ($CheckOnly) {
    Write-Host "[3/3] Startup check passed." -ForegroundColor Green
    exit 0
}

if (Test-LocalPort 8000) {
    Stop-WithMessage "Port 8000 is already in use. Stop the old backend service first."
}
if (Test-LocalPort 5173) {
    Stop-WithMessage "Port 5173 is already in use. Stop the old frontend service first."
}

$BackendProcess = $null
$FrontendProcess = $null
try {
    Write-Host "[3/3] Starting backend and frontend..." -ForegroundColor Yellow
    $BackendProcess = Start-ChildProcess `
        -FilePath $Python `
        -Arguments "`"$BackendScript`"" `
        -WorkingDirectory $Root

    $FrontendProcess = Start-ChildProcess `
        -FilePath $Node `
        -Arguments "`"$ViteScript`"" `
        -WorkingDirectory $FrontendDir

    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    @{
        backend = $BackendProcess.Id
        frontend = $FrontendProcess.Id
        started_at = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Seconds 1
        $BackendProcess.Refresh()
        $FrontendProcess.Refresh()
        if ($BackendProcess.HasExited) {
            throw "Backend exited with code $($BackendProcess.ExitCode)."
        }
        if ($FrontendProcess.HasExited) {
            throw "Frontend exited with code $($FrontendProcess.ExitCode)."
        }
        try {
            $health = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/health/ready" `
                -UseBasicParsing `
                -TimeoutSec 1
            if ($health.StatusCode -eq 200 -and (Test-LocalPort 5173)) {
                $ready = $true
                break
            }
        }
        catch {
            # Services are still starting.
        }
    }

    if (-not $ready) {
        throw "Services were not ready within 60 seconds. Check the logs above."
    }

    Write-Host ""
    Write-Host "Ready: http://localhost:5173" -ForegroundColor Green
    Write-Host "Keep this window open. Press Ctrl+C to stop all services." -ForegroundColor Cyan
    Write-Host ""
    if ($SmokeTest) {
        Write-Host "Smoke test passed." -ForegroundColor Green
        return
    }
    if (-not $NoBrowser) {
        Open-ApplicationPage
    }

    while ($true) {
        Start-Sleep -Seconds 2
        $BackendProcess.Refresh()
        $FrontendProcess.Refresh()
        if ($BackendProcess.HasExited -or $FrontendProcess.HasExited) {
            throw "A service exited unexpectedly. Check the logs above."
        }
    }
}
catch {
    Write-Host ""
    Write-Host "[RUNTIME ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Write-Host "Stopping services..." -ForegroundColor Yellow
    Stop-ProcessTree $FrontendProcess
    Stop-ProcessTree $BackendProcess
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}
