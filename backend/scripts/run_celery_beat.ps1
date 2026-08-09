# Start Celery beat — schedules the transfer poller + Claimed-event reconciler
# (schedule defined in app/worker.py; cadence via TRANSFER_POLL_INTERVAL_SECONDS /
# RECONCILE_INTERVAL_SECONDS). A worker (run_celery_worker.ps1) must also be
# running to execute the scheduled tasks. Don't run beat in dev unless you want
# real Moralis calls on a timer.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "Starting Celery beat..."
.\.venv\Scripts\celery.exe -A app.worker:celery_app beat --loglevel=info
