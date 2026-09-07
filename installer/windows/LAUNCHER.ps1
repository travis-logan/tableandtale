$ErrorActionPreference = "Stop"
$installer = Join-Path $PSScriptRoot "INSTALLER.ps1"
if(-not (Test-Path $installer)){
    Write-Host "INSTALLER.ps1 is missing. Re-extract the ZIP and try again." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($installer,[ref]$tokens,[ref]$parseErrors) | Out-Null
if($parseErrors -and $parseErrors.Count -gt 0){
    Write-Host "The installer package failed its PowerShell syntax check and was NOT run." -ForegroundColor Red
    Write-Host "" 
    foreach($e in $parseErrors){Write-Host $e.Message -ForegroundColor Red}
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

$quotedInstaller = '"' + $installer + '"'
$args = "-NoProfile -ExecutionPolicy Bypass -NoExit -File " + $quotedInstaller
Start-Process powershell.exe -Verb RunAs -ArgumentList $args
