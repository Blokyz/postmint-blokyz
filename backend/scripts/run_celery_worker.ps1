# Start a single Celery ingestion worker (Windows-safe solo pool).
# Stops stray celery.exe processes first to avoid DuplicateNodenameWarning.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Get-CimInstance Win32_Process -Filter "Name = 'celery.exe'" -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "Stopping celery.exe PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep -Seconds 1

Write-Host "Starting ingestion worker (solo pool)..."
.\.venv\Scripts\celery.exe -A app.worker:celery_app worker -Q ingestion --loglevel=info
