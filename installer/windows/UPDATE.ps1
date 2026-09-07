param([string]$InstallDir="C:\FamilyCookbook")
$ErrorActionPreference="Stop"
$Host.UI.RawUI.WindowTitle="Table & Tale v3.2.2 Public Sharing Update"
$SourceRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload=Join-Path $SourceRoot "payload"
$TaskName="FamilyCookbookServerV2"

function Fail([string]$m){Write-Host "";Write-Host "UPDATE STOPPED" -ForegroundColor Red;Write-Host $m -ForegroundColor Red;Read-Host "Press Enter to close";exit 1}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){Fail "Run this update as Administrator."}

$config=Join-Path $InstallDir "config.json"
$db=Join-Path $InstallDir "data\cookbook.db"
$app=Join-Path $InstallDir "app"
if(-not (Test-Path $config) -or -not (Test-Path $db) -or -not (Test-Path $app)){Fail "Existing Table & Tale installation was not found."}
$cfg=Get-Content $config -Raw|ConvertFrom-Json
$port=if($cfg.port){[int]$cfg.port}else{3000}

function Health {
  try{return Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 3 -ErrorAction Stop}catch{return $null}
}
$before=Health
if(-not $before){Fail "The current cookbook is not healthy. No files were changed."}
$users=[int]$before.users
$schema=[string]$before.schema_version

$stamp=Get-Date -Format "yyyy-MM-dd_HHmmss"
$backup=Join-Path $InstallDir ("backups\pre-3.2.2-sharing-"+$stamp)
New-Item -ItemType Directory $backup -Force|Out-Null
Copy-Item $app (Join-Path $backup "app") -Recurse -Force
if(Test-Path (Join-Path $InstallDir "VERSION")){Copy-Item (Join-Path $InstallDir "VERSION") (Join-Path $backup "VERSION") -Force}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{$_.CommandLine -and $_.CommandLine -like "*$InstallDir*app.py*"}|ForEach-Object{Stop-Process $_.ProcessId -Force -ErrorAction SilentlyContinue}

try{
  Remove-Item $app -Recurse -Force
  Copy-Item (Join-Path $Payload "app") $app -Recurse -Force
  Copy-Item (Join-Path $Payload "VERSION") (Join-Path $InstallDir "VERSION") -Force
  Start-ScheduledTask -TaskName $TaskName
  $after=$null
  for($i=0;$i -lt 30;$i++){Start-Sleep -Milliseconds 700;$after=Health;if($after){break}}
  if(-not $after){throw "Server did not become healthy."}
  if([string]$after.app_version -ne "3.2.2"){throw "Expected v3.2.2 but server reports $($after.app_version)."}
  if([int]$after.users -ne $users){throw "User validation failed."}
  if([string]$after.schema_version -ne $schema){throw "Database schema unexpectedly changed."}
  $launch=Get-Date -Format "yyyyMMddHHmmss"
  Start-Process "http://localhost:$port/?_appv=3.2.2&_refresh=$launch"
  Write-Host ""
  Write-Host "UPDATE COMPLETE - Table & Tale v3.2.2" -ForegroundColor Green
  Write-Host "Users preserved: $users | Schema unchanged: $schema" -ForegroundColor Green
  Write-Host "Open Admin > Public Sharing to review the public URL." -ForegroundColor Cyan
  Read-Host "Press Enter to close"
}catch{
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if(Test-Path $app){Remove-Item $app -Recurse -Force}
  Copy-Item (Join-Path $backup "app") $app -Recurse -Force
  if(Test-Path (Join-Path $backup "VERSION")){Copy-Item (Join-Path $backup "VERSION") (Join-Path $InstallDir "VERSION") -Force}
  Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Fail ("Update failed and previous app files were restored: "+$_.Exception.Message)
}
