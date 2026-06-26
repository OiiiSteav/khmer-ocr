# Automated Git Push Script
# Ensures changes are committed and uploaded to your GitHub repository in one command.

$ErrorActionPreference = "Stop"

# Check if Git is installed
try {
    $null = git --version
} catch {
    Write-Host "Error: Git is not installed or not in your PATH." -ForegroundColor Red
    Write-Host "Please install Git by running this command in an Administrator PowerShell window:" -ForegroundColor Yellow
    Write-Host "winget install --id Git.Git --silent" -ForegroundColor Cyan
    exit
}

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  GitHub Automated Publisher" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan

# 1. Initialize Git repository if not already done
if (-not (Test-Path ".git")) {
    Write-Host "Initializing local Git repository..." -ForegroundColor Yellow
    git init
    git branch -M main
}

# 2. Check if remote origin is configured
$RemoteUrl = "https://github.com/OiiiSteav/khmer-ocr.git"
try {
    $CurrentRemote = git remote get-url origin 2>$null
    if ($CurrentRemote -ne $RemoteUrl) {
        Write-Host "Updating remote origin to point to: $RemoteUrl" -ForegroundColor Yellow
        git remote set-url origin $RemoteUrl
    }
} catch {
    Write-Host "Setting remote origin to: $RemoteUrl" -ForegroundColor Yellow
    git remote add origin $RemoteUrl
    git branch -M main
}

# 3. Stage all changes
Write-Host "`nStaging all local files..." -ForegroundColor Yellow
git add -A

# 4. Prompt for commit message
$Message = Read-Host -Prompt "Enter a commit message (default: 'Update')"
if ([string]::IsNullOrWhiteSpace($Message)) {
    $Message = "Update code and assets"
}

# 5. Commit changes
Write-Host "Committing changes..." -ForegroundColor Yellow
try {
    git commit -m $Message
} catch {
    Write-Host "No changes to commit or commit failed." -ForegroundColor Gray
}

# 6. Push to GitHub
Write-Host "`nPushing to GitHub (main branch)..." -ForegroundColor Yellow
Write-Host "Note: If this is your first time, a Windows dialog will pop up asking you to sign into GitHub." -ForegroundColor Cyan

# Run standard push
git push -u origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nStandard push failed." -ForegroundColor Yellow
    Write-Host "This usually happens because you previously uploaded files via the web browser, causing a history mismatch." -ForegroundColor White
    $Choice = Read-Host -Prompt "Would you like to FORCE push to overwrite the remote history with your local files? (y/n)"
    
    if ($Choice -eq "y" -or $Choice -eq "Y") {
        Write-Host "`nForce pushing to GitHub..." -ForegroundColor Yellow
        git push -u origin main --force
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "`n===============================================" -ForegroundColor Green
            Write-Host "  Success! Your code has been pushed to GitHub." -ForegroundColor Green
            Write-Host "===============================================" -ForegroundColor Green
        } else {
            Write-Host "`nForce push failed. Please check your internet connection or GitHub permissions." -ForegroundColor Red
        }
    } else {
        Write-Host "`nPush cancelled. Your local files were committed but not uploaded." -ForegroundColor Gray
    }
} else {
    Write-Host "`n===============================================" -ForegroundColor Green
    Write-Host "  Success! Your code has been pushed to GitHub." -ForegroundColor Green
    Write-Host "===============================================" -ForegroundColor Green
}

Write-Host "`nPress any key to exit..."
[void][System.Console]::ReadKey($true)
