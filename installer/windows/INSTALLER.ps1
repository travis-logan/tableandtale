param(
    [string]$InstallDir = "C:\FamilyCookbook"
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Table & Tale Installer v3.2.1"
$InstallerLog = Join-Path $env:TEMP "TableAndTaleInstaller.log"
try { Start-Transcript -Path $InstallerLog -Append | Out-Null } catch {}

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload = Join-Path $SourceRoot "payload"
$HelperPath = Join-Path $SourceRoot "installer_helper.py"
$ServerTask = "FamilyCookbookServerV2"
$BackupTask = "FamilyCookbookBackupV2"
$RuleName = "Family Cookbook Private LAN"

function Banner {
    Clear-Host
    Write-Host ""
    Write-Host "  TABLE & TALE" -ForegroundColor DarkYellow
    Write-Host "  Family Cookbook Server v3.2.1" -ForegroundColor Green
    Write-Host "  ===========================" -ForegroundColor DarkGreen
    Write-Host ""
}

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "INSTALLATION STOPPED" -ForegroundColor Red
    Write-Host $Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Installer log: $InstallerLog" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

function Require-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail "This installer must run as Administrator."
    }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
}

function Find-Python {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        try { & python --version *> $null; if ($LASTEXITCODE -eq 0) { return "python" } } catch {}
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { & py -3 --version *> $null; if ($LASTEXITCODE -eq 0) { return "py -3" } } catch {}
    }
    return $null
}

function Invoke-Python([string]$PythonCommand,[string[]]$Arguments) {
    if ($PythonCommand -eq "py -3") { & py -3 @Arguments } else { & python @Arguments }
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $PythonCommand $($Arguments -join ' ')" }
}

function Invoke-InstallerHelper([string]$Python,[string[]]$Arguments) {
    $resultFile = Join-Path $env:TEMP ("TableAndTaleHelper-" + [Guid]::NewGuid().ToString("N") + ".json")
    $previousPreference = $ErrorActionPreference
    $exitCode = -1
    try {
        $ErrorActionPreference = "Continue"
        & $Python $HelperPath @Arguments "--output" $resultFile
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    if (-not (Test-Path $resultFile)) {
        return [pscustomobject]@{ok=$false;error="Installer helper did not produce a result file.";traceback="";exit_code=$exitCode}
    }

    try {
        $result = Get-Content $resultFile -Raw | ConvertFrom-Json
    }
    catch {
        $result = [pscustomobject]@{ok=$false;error=("Could not read installer helper result: " + $_.Exception.Message);traceback=""}
    }
    finally {
        Remove-Item $resultFile -Force -ErrorAction SilentlyContinue
    }

    $result | Add-Member -NotePropertyName exit_code -NotePropertyValue $exitCode -Force
    return $result
}

function Get-DbInfo([string]$Python,[string]$Db) {
    if (-not (Test-Path $Db)) {
        return [pscustomobject]@{ok=$false;error="Database file is missing.";user_count=0;user_fingerprint="";schema_version="unknown"}
    }
    if (-not (Test-Path $Python)) {
        return [pscustomobject]@{ok=$false;error="Cookbook Python environment is missing.";user_count=0;user_fingerprint="";schema_version="unknown"}
    }
    return Invoke-InstallerHelper $Python @("db-info","--db",$Db)
}

function Backup-ExistingInstall([string]$Path,[string]$Python,[string]$Db) {
    $stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
    $folder = Join-Path $Path ("backups\pre-upgrade-" + $stamp)
    New-Item -ItemType Directory -Force $folder | Out-Null

    $dbBackup = Join-Path $folder "cookbook.db"
    $backupResult = Invoke-InstallerHelper $Python @("backup-db","--db",$Db,"--dest",$dbBackup)
    if (-not $backupResult.ok) {
        Write-Host ("Database backup failed: " + $backupResult.error) -ForegroundColor Red
        if ($backupResult.traceback) { Write-Host $backupResult.traceback -ForegroundColor DarkRed }
        Remove-Item $folder -Recurse -Force -ErrorAction SilentlyContinue
        return $null
    }

    foreach($name in @("app","requirements.txt","run-server.ps1","backup.py","server-status.ps1","VERSION")) {
        $src = Join-Path $Path $name
        if(Test-Path $src){ Copy-Item $src (Join-Path $folder $name) -Recurse -Force }
    }
    return $folder
}

function Stop-CookbookServer([string]$Path) {
    Stop-ScheduledTask -TaskName $ServerTask -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and (
          (($_.Name -in @('python.exe','pythonw.exe')) -and $_.CommandLine.IndexOf($Path,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.CommandLine.IndexOf('app.py',[StringComparison]::OrdinalIgnoreCase) -ge 0) -or
          (($_.Name -in @('powershell.exe','pwsh.exe')) -and $_.CommandLine.IndexOf($Path,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.CommandLine.IndexOf('run-server.ps1',[StringComparison]::OrdinalIgnoreCase) -ge 0)
        )
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 700
}

function Wait-PortFree([int]$Port,[string]$Path,[int]$Seconds=10) {
    for($i=0;$i -lt $Seconds;$i++){
        $listeners=Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        if(-not $listeners){return $true}
        foreach($l in $listeners){
            try{
                $pr=Get-CimInstance Win32_Process -Filter "ProcessId=$($l.OwningProcess)" -ErrorAction SilentlyContinue
                if($pr -and $pr.CommandLine -and $pr.CommandLine.IndexOf($Path,[StringComparison]::OrdinalIgnoreCase) -ge 0){Stop-Process -Id $l.OwningProcess -Force -ErrorAction SilentlyContinue}
            }catch{}
        }
        Start-Sleep 1
    }
    return -not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Test-Health([int]$Port,[int]$Attempts=20,[int]$DelayMs=750) {
    for($i=0;$i -lt $Attempts;$i++){
        try{
            $h=Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2 -ErrorAction Stop
            if($h.ok){return $h}
        }catch{}
        Start-Sleep -Milliseconds $DelayMs
    }
    return $null
}

function Restore-Upgrade([string]$Path,[string]$BackupFolder,[int]$Port,[int]$ExpectedUsers) {
    Write-Host "Upgrade validation failed. Restoring the previous working version..." -ForegroundColor Yellow
    Stop-CookbookServer $Path
    $liveDb=Join-Path $Path "data\cookbook.db"
    Remove-Item ($liveDb+"-wal") -Force -ErrorAction SilentlyContinue
    Remove-Item ($liveDb+"-shm") -Force -ErrorAction SilentlyContinue
    if(Test-Path (Join-Path $BackupFolder "cookbook.db")) { Copy-Item (Join-Path $BackupFolder "cookbook.db") $liveDb -Force }
    foreach($name in @("app","requirements.txt","run-server.ps1","backup.py","server-status.ps1","VERSION")) {
        $src=Join-Path $BackupFolder $name; $dest=Join-Path $Path $name
        if(Test-Path $src){ if(Test-Path $dest){Remove-Item $dest -Recurse -Force}; Copy-Item $src $dest -Recurse -Force }
    }
    Start-ScheduledTask -TaskName $ServerTask -ErrorAction SilentlyContinue
    $old=Test-Health $Port 25 800
    if($old){
        Write-Host "ROLLBACK SUCCESSFUL. Previous cookbook is responding again. Users: $($old.users)." -ForegroundColor Green
        if($ExpectedUsers -gt 0 -and [int]$old.users -lt $ExpectedUsers){Write-Host "WARNING: rollback health check reports fewer users than expected." -ForegroundColor Red}
    } else {
        Write-Host "WARNING: files were restored, but the previous server did not answer its health check automatically." -ForegroundColor Red
    }
}

function Schedule-SelfCleanup([string]$SourceFolder,[string]$InstalledFolder) {
    try {
        $sourceFull=[IO.Path]::GetFullPath($SourceFolder).TrimEnd('\')
        $installFull=[IO.Path]::GetFullPath($InstalledFolder).TrimEnd('\')
        if ($sourceFull -eq $installFull -or $installFull.StartsWith($sourceFull+'\',[StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "Automatic installer cleanup skipped because the install directory is inside the extracted folder." -ForegroundColor Yellow
            return
        }
        $escaped=$sourceFull.Replace("'","''")
        $cmd="Start-Sleep -Seconds 4; Remove-Item -LiteralPath '$escaped' -Recurse -Force -ErrorAction SilentlyContinue"
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-Command",$cmd) | Out-Null
        Write-Host "The extracted installer folder will delete itself after this window closes." -ForegroundColor Green
    } catch { Write-Host "Automatic cleanup could not be scheduled. You may delete the extracted installer folder manually." -ForegroundColor Yellow }
}

function Show-Diagnostics([string]$StdOut,[string]$StdErr) {
    Write-Host ""
    Write-Host "STARTUP DIAGNOSTICS" -ForegroundColor Yellow
    Write-Host "-------------------" -ForegroundColor DarkYellow
    if(Test-Path $StdErr){
        $err=Get-Content $StdErr -Tail 80 -ErrorAction SilentlyContinue
        if($err){Write-Host ($err -join "`n") -ForegroundColor Red}
    }
    if(Test-Path $StdOut){
        $out=Get-Content $StdOut -Tail 40 -ErrorAction SilentlyContinue
        if($out){Write-Host ($out -join "`n") -ForegroundColor Gray}
    }
    Write-Host ""
}

Banner
Require-Admin
if(-not (Test-Path $Payload)){Fail "Installer payload is missing. Re-extract the ZIP and try again."}
if(-not (Test-Path $HelperPath)){Fail "Installer helper is missing. Re-extract the ZIP and try again."}

Write-Host "Install location: $InstallDir" -ForegroundColor Cyan
$answer=Read-Host "Press Enter to use this folder, or enter another full path"
if($answer.Trim()){ $InstallDir=$answer.Trim().Trim('"') }
New-Item -ItemType Directory -Force $InstallDir | Out-Null

$existingDb=Join-Path $InstallDir "data\cookbook.db"
$upgrade=Test-Path $existingDb
$existingPython=Join-Path $InstallDir ".venv\Scripts\python.exe"
$userCountBefore=0;$userFingerprintBefore="";$rollbackFolder=$null

Write-Host "[1/11] Preparing the cookbook server..." -ForegroundColor Yellow
if($upgrade){
    Write-Host "Existing cookbook detected. This will be an in-place upgrade." -ForegroundColor Green
    if(-not (Test-Path $HelperPath)){Fail "Installer helper is missing. Re-extract the ZIP and try again."}
    $beforeInfo=Get-DbInfo $existingPython $existingDb
    if(-not $beforeInfo.ok){Fail ("Could not verify the existing cookbook before upgrade: " + $beforeInfo.error)}
    $userCountBefore=[int]$beforeInfo.user_count
    $userFingerprintBefore=[string]$beforeInfo.user_fingerprint
    Stop-CookbookServer $InstallDir
    $rollbackFolder=Backup-ExistingInstall $InstallDir $existingPython $existingDb
    if(-not $rollbackFolder){Fail "Could not create the pre-upgrade database backup. Nothing was upgraded."}
    Write-Host "Pre-upgrade restore point created: $rollbackFolder" -ForegroundColor Green
    Write-Host "Existing user records detected: $userCountBefore" -ForegroundColor Green
}

Write-Host "[2/11] Installing Table & Tale application files..." -ForegroundColor Yellow
foreach($item in (Get-ChildItem $Payload -Force)){
    if($item.Name -in @("uploads","backups","logs",".venv","config.json")){continue}
    $dest=Join-Path $InstallDir $item.Name
    if($item.Name -eq "data"){
        New-Item -ItemType Directory -Force $dest | Out-Null
        Get-ChildItem $item.FullName -Force | Where-Object {$_.Name -ne "cookbook.db"} | ForEach-Object { Copy-Item $_.FullName (Join-Path $dest $_.Name) -Recurse -Force }
        continue
    }
    if(Test-Path $dest){Remove-Item $dest -Recurse -Force}
    Copy-Item $item.FullName $dest -Recurse -Force
}
New-Item -ItemType Directory -Force (Join-Path $InstallDir "uploads") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallDir "backups") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallDir "logs") | Out-Null
Set-Location $InstallDir

Write-Host "[3/11] Checking Python..." -ForegroundColor Yellow
$pythonCommand=Find-Python
if(-not $pythonCommand){
    if(-not (Get-Command winget -ErrorAction SilentlyContinue)){if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder 3000 $userCountBefore};Fail "Windows Package Manager (winget) is required."}
    winget install --id Python.Python.3.13 -e --accept-package-agreements --accept-source-agreements
    if($LASTEXITCODE -ne 0){if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder 3000 $userCountBefore};Fail "Python installation failed."}
    Refresh-Path;Start-Sleep 2;$pythonCommand=Find-Python
    if(-not $pythonCommand){if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder 3000 $userCountBefore};Fail "Python installed but PATH has not refreshed. Restart Windows and retry."}
}

Write-Host "[4/11] Creating/updating the private Python environment..." -ForegroundColor Yellow
$venvPython=Join-Path $InstallDir ".venv\Scripts\python.exe"
if(-not (Test-Path $venvPython)){Invoke-Python $pythonCommand @("-m","venv",".venv")}
& $venvPython -m pip install --upgrade pip --disable-pip-version-check
if($LASTEXITCODE -ne 0){if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder 3000 $userCountBefore};Fail "Could not update pip."}
& $venvPython -m pip install -r (Join-Path $InstallDir "requirements.txt") --disable-pip-version-check
if($LASTEXITCODE -ne 0){if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder 3000 $userCountBefore};Fail "Could not install cookbook dependencies."}

Write-Host "[5/11] Preflighting the database migration on a COPY..." -ForegroundColor Yellow
if($upgrade){
    $preDir=Join-Path $env:TEMP ("TableAndTalePreflight-"+[Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force $preDir|Out-Null
    $preDb=Join-Path $preDir "cookbook.db";Copy-Item (Join-Path $rollbackFolder "cookbook.db") $preDb -Force
    $preData=Join-Path $preDir "data";New-Item -ItemType Directory -Force $preData|Out-Null
    Copy-Item $preDb (Join-Path $preData "cookbook.db") -Force
    if(Test-Path (Join-Path $Payload "data\seed_recipes.json")){Copy-Item (Join-Path $Payload "data\seed_recipes.json") (Join-Path $preData "seed_recipes.json") -Force}
    $preUploads=Join-Path $preDir "uploads";New-Item -ItemType Directory -Force $preUploads|Out-Null
    $preApp=Join-Path $Payload "app\app.py"
    $preLiveDb=Join-Path $preData "cookbook.db"
    $pr=Invoke-InstallerHelper $venvPython @("preflight","--app",$preApp,"--db",$preLiveDb,"--data",$preData,"--uploads",$preUploads)
    Remove-Item $preDir -Recurse -Force -ErrorAction SilentlyContinue
    $preflightBad = (-not $pr.ok) -or ([string]$pr.schema_version -ne "3") -or ([int]$pr.user_count -ne $userCountBefore)
    if($userFingerprintBefore -and ([string]$pr.user_fingerprint -ne $userFingerprintBefore)){$preflightBad=$true}
    if($preflightBad){
        Write-Host "Migration preflight failed before the live database was touched." -ForegroundColor Red
        if($pr.error){Write-Host $pr.error -ForegroundColor Red}
        if($pr.traceback){Write-Host $pr.traceback -ForegroundColor DarkRed}
        Restore-Upgrade $InstallDir $rollbackFolder 3000 $userCountBefore
        Fail "v3.2.1 migration preflight failed. Your previous cookbook was restored."
    }
    Write-Host "Migration preflight passed. Existing users are unchanged on the test copy." -ForegroundColor Green
}else{Write-Host "Fresh install, migration preflight not required." -ForegroundColor DarkGray}

Write-Host "[6/11] Installing recipe-card OCR support..." -ForegroundColor Yellow
$tesseractCandidates=@("C:\Program Files\Tesseract-OCR\tesseract.exe","C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")
$tesseractFound=$false;foreach($t in $tesseractCandidates){if(Test-Path $t){$tesseractFound=$true}}
if(-not $tesseractFound -and (Get-Command tesseract -ErrorAction SilentlyContinue)){$tesseractFound=$true}
if(-not $tesseractFound -and (Get-Command winget -ErrorAction SilentlyContinue)){
    winget install --id UB-Mannheim.TesseractOCR -e --accept-package-agreements --accept-source-agreements
    if($LASTEXITCODE -ne 0){Write-Host "OCR install did not complete. The cookbook will still work; photo transcription will be unavailable until Tesseract is installed." -ForegroundColor Yellow}
}else{Write-Host "Tesseract OCR found or already available." -ForegroundColor Green}

Write-Host "[7/11] Verifying server configuration..." -ForegroundColor Yellow
$configPath=Join-Path $InstallDir "config.json";$port=3000
if(Test-Path $configPath){try{$cfg=Get-Content $configPath -Raw|ConvertFrom-Json;if($cfg.port){$port=[int]$cfg.port}}catch{if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder 3000 $userCountBefore};Fail "Existing config.json could not be read."}}
else{
    $bytes=New-Object byte[] 32;$rng=New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    try{$rng.GetBytes($bytes)}finally{$rng.Dispose()};$secret=-join($bytes|ForEach-Object{$_.ToString("x2")})
    $json=@{secret_key=$secret;port=$port;site_name="Table & Tale";allow_lan=$true}|ConvertTo-Json
    [IO.File]::WriteAllText($configPath,$json,(New-Object System.Text.UTF8Encoding($false)))
}

Write-Host "[8/11] Configuring Windows startup, firewall and backups..." -ForegroundColor Yellow
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue|Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private|Out-Null
$runner=Join-Path $InstallDir "run-server.ps1"
$action=New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`""
$trigger=New-ScheduledTaskTrigger -AtStartup
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $ServerTask -InputObject (New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal) -Force|Out-Null
$backupAction=New-ScheduledTaskAction -Execute $venvPython -Argument "`"$(Join-Path $InstallDir 'backup.py')`""
$backupTrigger=New-ScheduledTaskTrigger -Daily -At 3am
$backupPrincipal=New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $BackupTask -InputObject (New-ScheduledTask -Action $backupAction -Trigger $backupTrigger -Principal $backupPrincipal) -Force|Out-Null

Write-Host "[9/11] Starting v3.2.1 in diagnostic mode..." -ForegroundColor Yellow
Stop-CookbookServer $InstallDir
if(-not (Wait-PortFree $port $InstallDir 10)){
    $busy=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue|Select-Object -First 1
    if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder $port $userCountBefore}
    Fail "Port $port is still occupied by process $($busy.OwningProcess). Close that process and retry."
}
$diagOut=Join-Path $InstallDir "logs\v3.2.1-startup.stdout.log";$diagErr=Join-Path $InstallDir "logs\v3.2.1-startup.stderr.log"
Remove-Item $diagOut,$diagErr -Force -ErrorAction SilentlyContinue
$oldPort=$env:COOKBOOK_PORT;$oldHost=$env:COOKBOOK_HOST
$env:COOKBOOK_PORT=[string]$port;$env:COOKBOOK_HOST="127.0.0.1"
$diag=Start-Process -FilePath $venvPython -ArgumentList @((Join-Path $InstallDir 'app\app.py')) -WorkingDirectory $InstallDir -RedirectStandardOutput $diagOut -RedirectStandardError $diagErr -PassThru -WindowStyle Hidden
$health=$null
for($i=0;$i -lt 30;$i++){
    Start-Sleep -Milliseconds 750
    if($diag.HasExited){break}
    try{$health=Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2 -ErrorAction Stop;if($health.ok){break}}catch{}
}
if($null -eq $oldPort){Remove-Item Env:COOKBOOK_PORT -ErrorAction SilentlyContinue}else{$env:COOKBOOK_PORT=$oldPort}
if($null -eq $oldHost){Remove-Item Env:COOKBOOK_HOST -ErrorAction SilentlyContinue}else{$env:COOKBOOK_HOST=$oldHost}

if(-not $health -or -not $health.ok){
    if(-not $diag.HasExited){Stop-Process -Id $diag.Id -Force -ErrorAction SilentlyContinue}
    Show-Diagnostics $diagOut $diagErr
    if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder $port $userCountBefore}
    Fail "v3.2.1 did not start successfully. The exact Python startup error is shown above and saved under C:\FamilyCookbook\logs."
}

Write-Host "[10/11] Validating database and existing users..." -ForegroundColor Yellow
$validationOk=$true
if($health.schema_version -ne "3"){$validationOk=$false;Write-Host "Schema validation failed: expected 3, got $($health.schema_version)." -ForegroundColor Red}
if($upgrade){
    $afterInfo=Get-DbInfo $venvPython $existingDb
    if(-not $afterInfo.ok){
        $validationOk=$false
        Write-Host ("Could not inspect upgraded user records: " + $afterInfo.error) -ForegroundColor Red
    } else {
        $afterCount=[int]$afterInfo.user_count
        $afterFp=[string]$afterInfo.user_fingerprint
        if($afterCount -ne $userCountBefore){$validationOk=$false;Write-Host "User-count validation failed: before=$userCountBefore after=$afterCount" -ForegroundColor Red}
        if($userFingerprintBefore -and $afterFp -ne $userFingerprintBefore){$validationOk=$false;Write-Host "Existing user records changed unexpectedly. Password/account fingerprint validation failed." -ForegroundColor Red}
    }
}
if(-not $validationOk){
    if(-not $diag.HasExited){Stop-Process -Id $diag.Id -Force -ErrorAction SilentlyContinue}
    if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder $port $userCountBefore}
    Fail "v3.2.1 database validation failed. The previous cookbook was restored."
}
Write-Host "Diagnostic launch healthy. Schema $($health.schema_version). Existing user records preserved." -ForegroundColor Green

# Hand off from the diagnostic process to the normal startup task.
if(-not $diag.HasExited){Stop-Process -Id $diag.Id -Force -ErrorAction SilentlyContinue}
Start-Sleep -Milliseconds 800
Start-ScheduledTask -TaskName $ServerTask
$taskHealth=Test-Health $port 30 700
if(-not $taskHealth){
    Show-Diagnostics (Join-Path $InstallDir 'logs\server.log') (Join-Path $InstallDir 'logs\server.log')
    if($upgrade){Restore-Upgrade $InstallDir $rollbackFolder $port $userCountBefore}
    Fail "v3.2.1 passed diagnostic startup but the Windows background task did not become healthy. The previous cookbook was restored."
}

Write-Host "[11/11] Finishing installation..." -ForegroundColor Yellow
$localIp=(Get-NetIPAddress -AddressFamily IPv4|Where-Object{$_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" -and $_.PrefixOrigin -ne "WellKnown"}|Sort-Object InterfaceMetric|Select-Object -First 1 -ExpandProperty IPAddress)
$desktop=[Environment]::GetFolderPath("Desktop")
"@echo off`r`nstart `"`" `"http://localhost:$port`""|Set-Content (Join-Path $desktop "Open Table and Tale.bat") -Encoding ASCII
"@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -NoExit -File `"$InstallDir\server-status.ps1`""|Set-Content (Join-Path $desktop "Table and Tale Status.bat") -Encoding ASCII

Banner
if($upgrade){Write-Host "UPGRADE COMPLETE" -ForegroundColor Green}else{Write-Host "INSTALLATION COMPLETE" -ForegroundColor Green}
Write-Host ""
Write-Host "Table & Tale v$($taskHealth.app_version) is running." -ForegroundColor Green
Write-Host "Existing cookbook users: $($taskHealth.users)" -ForegroundColor Green
Write-Host "Schema: $($taskHealth.schema_version)" -ForegroundColor Green
Write-Host ""
Write-Host "On this PC: http://localhost:$port" -ForegroundColor Cyan
if($localIp){Write-Host "Home network: http://${localIp}:$port" -ForegroundColor Cyan}
if($upgrade){Write-Host "Your previous version remains backed up at: $rollbackFolder" -ForegroundColor White}
Write-Host ""
$launchStamp=Get-Date -Format "yyyyMMddHHmmss"
Start-Process "http://localhost:$port/?_appv=3.2.1&_refresh=$launchStamp"
Schedule-SelfCleanup $SourceRoot $InstallDir
Read-Host "Press Enter to close the installer"
