$ErrorActionPreference="Continue"
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$logDir=Join-Path $Root "logs"
New-Item -ItemType Directory -Force $logDir|Out-Null
$log=Join-Path $logDir "server.log"

try {
    $config=Get-Content (Join-Path $Root "config.json") -Raw | ConvertFrom-Json
} catch {
    Add-Content $log "[$(Get-Date -Format s)] RUNNER CONFIG ERROR: $($_.Exception.Message)"
    exit 1
}

$python=Join-Path $Root ".venv\Scripts\python.exe"
if(-not (Test-Path $python)){
    Add-Content $log "[$(Get-Date -Format s)] RUNNER ERROR: Python environment missing at $python"
    exit 1
}

$env:COOKBOOK_PORT=[string]$config.port
$env:COOKBOOK_HOST="0.0.0.0"

while($true){
    Add-Content $log "[$(Get-Date -Format s)] Starting Table & Tale server..."
    # Keep ErrorActionPreference at Continue so Windows PowerShell 5.1 does not
    # abort on the first stderr line and lose the actual Python traceback.
    & $python (Join-Path $Root "app\app.py") *>> $log
    $exit=$LASTEXITCODE
    Add-Content $log "[$(Get-Date -Format s)] Server process exited with code $exit. Restarting in 5 seconds."
    Start-Sleep -Seconds 5
}
