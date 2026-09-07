param(
    [switch]$SkipVision,
    [string]$InstallDir = "C:\FamilyCookbook"
)
$ErrorActionPreference="Stop"

function Find-RecipeModelfile {
    $candidates=@(
        (Join-Path $InstallDir "ollama\Modelfile.recipe-chef"),
        (Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))) "ollama\Modelfile.recipe-chef")
    )
    foreach($p in $candidates){if(Test-Path -LiteralPath $p){return (Resolve-Path -LiteralPath $p).Path}}
    return $null
}

Write-Host ""
Write-Host "TABLE & TALE LOCAL AI BETA SETUP" -ForegroundColor Green
Write-Host "================================" -ForegroundColor DarkGreen
Write-Host ""

if(-not (Get-Command ollama -ErrorAction SilentlyContinue)){
    Write-Host "Ollama is not installed or is not on PATH." -ForegroundColor Yellow
    Write-Host "Install Ollama for Windows, reopen PowerShell, and run this script again."
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host "[1/5] Ollama detected:" -ForegroundColor Green
ollama --version

$modelfile=Find-RecipeModelfile
if(-not $modelfile){throw "Could not find ollama\Modelfile.recipe-chef"}

Write-Host "[2/5] Recipe Modelfile found: $modelfile" -ForegroundColor Green

Write-Host "[3/5] Checking Qwen3 8B..." -ForegroundColor Yellow
$list=(ollama list | Out-String)
if($list -match '(?im)^\s*qwen3:8b\s'){
    Write-Host "qwen3:8b already installed. Skipping download." -ForegroundColor Green
}else{
    ollama pull qwen3:8b
    if($LASTEXITCODE -ne 0){throw "Could not download qwen3:8b"}
}

Write-Host "[4/5] Creating Table & Tale recipe-chef model..." -ForegroundColor Yellow
ollama create tableandtale-chef -f $modelfile
if($LASTEXITCODE -ne 0){throw "Could not create tableandtale-chef"}

Write-Host "[5/5] Optional recipe-card vision model..." -ForegroundColor Yellow
if(-not $SkipVision){
    $list=(ollama list | Out-String)
    if($list -match '(?im)^\s*gemma3:4b\s'){Write-Host "gemma3:4b already installed." -ForegroundColor Green}
    else{ollama pull gemma3:4b}
}else{Write-Host "Vision model skipped." -ForegroundColor DarkGray}

Write-Host ""
Write-Host "LOCAL AI READY" -ForegroundColor Green
Write-Host "Admin -> Local AI -> model: tableandtale-chef" -ForegroundColor Cyan
Read-Host "Press Enter to close"
