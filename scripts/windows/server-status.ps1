$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$config=Get-Content "$Root\config.json" -Raw|ConvertFrom-Json
$task=Get-ScheduledTask "FamilyCookbookServerV2" -ErrorAction SilentlyContinue
Write-Host "Family Cookbook" -ForegroundColor Cyan
Write-Host "Server task: $($task.State)"
try{$h=Invoke-RestMethod "http://localhost:$($config.port)/health" -TimeoutSec 4;if($h.ok){Write-Host "Health: OK" -ForegroundColor Green}}catch{Write-Host "Health: NOT RESPONDING" -ForegroundColor Red}
$ip=(Get-NetIPAddress -AddressFamily IPv4|Where-Object{$_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*"}|Select-Object -First 1 -ExpandProperty IPAddress)
Write-Host "Local: http://localhost:$($config.port)"
if($ip){Write-Host "LAN:   http://${ip}:$($config.port)"}
if(Get-Command tailscale -ErrorAction SilentlyContinue){tailscale funnel status}
