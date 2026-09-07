$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $MyInvocation.MyCommand.Path
$config=Get-Content "$Root\config.json" -Raw|ConvertFrom-Json
$port=$config.port
Write-Host "Remote Access Setup" -ForegroundColor Cyan
Write-Host ""
Write-Host "1) Tailscale Funnel - easiest, stable *.ts.net HTTPS URL, no domain required."
Write-Host "2) Cloudflare Tunnel - best if you own a domain managed by Cloudflare."
Write-Host ""
$choice=Read-Host "Choose 1 or 2"
if($choice -eq "1"){
  if(-not (Get-Command tailscale -ErrorAction SilentlyContinue)){
    if(Get-Command winget -ErrorAction SilentlyContinue){
      winget install --id Tailscale.Tailscale --accept-package-agreements --accept-source-agreements
      $env:Path=[Environment]::GetEnvironmentVariable("Path","Machine")+";"+[Environment]::GetEnvironmentVariable("Path","User")
    }else{Write-Host "Install Tailscale, sign in, then rerun this script.";exit}
  }
  Write-Host "Tailscale may open a browser so you can sign in or authorize this PC." -ForegroundColor Yellow
  tailscale up
  Write-Host "Enabling Funnel in the background..."
  tailscale funnel --bg $port
  tailscale funnel status
  Write-Host ""
  Write-Host "IMPORTANT: Funnel is publicly reachable, but the cookbook itself still requires an account." -ForegroundColor Yellow
  Write-Host "Share cookbook invite codes, not your admin credentials." -ForegroundColor Yellow
}elseif($choice -eq "2"){
  Write-Host ""
  Write-Host "Cloudflare Tunnel needs a domain on Cloudflare." -ForegroundColor Yellow
  Write-Host "Create a remotely-managed Tunnel in Cloudflare, map a hostname such as cookbook.example.com to:"
  Write-Host "    http://localhost:$port" -ForegroundColor Cyan
  Write-Host "Then run Cloudflare's provided Windows service-install command with the tunnel token."
  Write-Host "Cloudflared will start at Windows boot and requires no router port forwarding."
}else{Write-Host "No changes made."}
