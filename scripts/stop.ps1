[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root ".run\processes.json"
$ProcessIds = New-Object System.Collections.Generic.List[int]

function Add-ProcessId {
    param([object]$Value)
    if ($null -ne $Value) {
        $parsed = 0
        if ([int]::TryParse([string]$Value, [ref]$parsed) -and $parsed -gt 0 -and
            -not $ProcessIds.Contains($parsed)) {
            $ProcessIds.Add($parsed)
        }
    }
}

function Get-PortProcessIds {
    param([int[]]$Ports)
    foreach ($port in $Ports) {
        try {
            Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop |
                ForEach-Object { Add-ProcessId $_.OwningProcess }
        }
        catch {
            $matches = netstat.exe -ano -p tcp | Select-String ":$port\s+.*LISTENING\s+(\d+)$"
            foreach ($match in $matches) {
                if ($match.Matches.Count -gt 0) {
                    Add-ProcessId $match.Matches[0].Groups[1].Value
                }
            }
        }
    }
}

function Get-ProjectProcessIds {
    try {
        $escapedRoot = [regex]::Escape($Root)
        Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object {
                $_.CommandLine -and $_.CommandLine -match $escapedRoot -and
                ($_.CommandLine -match "backend[\\/]run\.py" -or
                    $_.CommandLine -match "node_modules[\\/]vite")
            } |
            ForEach-Object { Add-ProcessId $_.ProcessId }
    }
    catch {
        # Port detection below remains available without CIM permissions.
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " EnterpriseMind Stopper" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (Test-Path $PidFile) {
    try {
        $saved = Get-Content -Raw $PidFile | ConvertFrom-Json
        Add-ProcessId $saved.backend
        Add-ProcessId $saved.frontend
    }
    catch {
        Write-Host "Saved process file is invalid; checking ports instead." -ForegroundColor Yellow
    }
}

Get-ProjectProcessIds
Get-PortProcessIds @(8000, 5173)

$Stopped = 0
foreach ($processId in $ProcessIds) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process) {
        continue
    }
    if ($process.ProcessName -notin @("python", "pythonw", "node")) {
        Write-Host "Skipped PID $processId ($($process.ProcessName)); it is not a project runtime." -ForegroundColor Yellow
        continue
    }
    Write-Host "Stopping PID $processId ($($process.ProcessName))..." -ForegroundColor Yellow
    & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
    $Stopped += 1
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue

if ($Stopped -eq 0) {
    Write-Host "No running EnterpriseMind service was found." -ForegroundColor Green
}
else {
    Write-Host "EnterpriseMind services stopped." -ForegroundColor Green
}
