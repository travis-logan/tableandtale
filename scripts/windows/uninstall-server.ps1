$ErrorActionPreference="SilentlyContinue"
Stop-ScheduledTask "FamilyCookbookServerV2"
Unregister-ScheduledTask "FamilyCookbookServerV2" -Confirm:$false
Unregister-ScheduledTask "FamilyCookbookBackupV2" -Confirm:$false
Remove-NetFirewallRule -DisplayName "Family Cookbook Private LAN"
Write-Host "Autostart/firewall rules removed. Database, uploads, and backups were NOT deleted." -ForegroundColor Green
