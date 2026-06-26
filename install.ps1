# Self-elevation check: Tesseract installation and copying language packs require Administrator rights.
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This script requires Administrator privileges to install Tesseract and register system components." -ForegroundColor Yellow
    Write-Host "Elevating privileges..." -ForegroundColor Cyan
    
    if ($PSCommandPath) {
        # Running from a local file on disk
        Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    } else {
        # Running remotely (in-memory via irm | iex). Save to a temp file and run it.
        $TempScriptPath = "$env:TEMP\khmer_ocr_install.ps1"
        try {
            $ScriptText = ""
            if ($MyInvocation.MyCommand.ScriptBlock) {
                $ScriptText = $MyInvocation.MyCommand.ScriptBlock.ToString()
            }
            if ([string]::IsNullOrWhiteSpace($ScriptText) -or $ScriptText.Length -lt 100) {
                # Fallback: Download from the known raw GitHub URL
                $ScriptText = Invoke-RestMethod -Uri "https://raw.githubusercontent.com/OiiiSteav/khmer-ocr/main/install.ps1" -UserAgent "Mozilla/5.0"
            }
            Set-Content -Path $TempScriptPath -Value $ScriptText -Encoding UTF8
            Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$TempScriptPath`"" -Verb RunAs
        } catch {
            Write-Host "Failed to elevate privileges automatically: $_" -ForegroundColor Red
            Write-Host "Please run PowerShell as Administrator first, and then execute the installer command." -ForegroundColor Yellow
        }
    }
    exit
}

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue" # Disables the blue progress bar to speed up downloads by up to 10x

# Configuration
$TargetDir = "$env:USERPROFILE\KhmerOCR"
$TesseractDefaultPath = "C:\Program Files\Tesseract-OCR"
$TessDataURL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/khm.traineddata"

# Dynamic Repository Detection
# If you rename the repo or if someone forks it, they can define $repo in their PowerShell session
# before running the script (e.g., $repo = "Username/repo-name"). The script will automatically adapt.
$DefaultRepo = "OiiiSteav/khmer-ocr"
$ActiveRepo = $DefaultRepo

if ($null -ne $repo -and $repo -ne "") {
    $ActiveRepo = $repo
    Write-Host "Custom repository detected in session: $ActiveRepo" -ForegroundColor Cyan
}

$RepoZipURL = "https://github.com/$ActiveRepo/archive/refs/heads/main.zip"

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  Offline Khmer OCR Installer for Windows" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan

# Step 1: Check and Install Tesseract OCR via Winget
Write-Host "`n[1/6] Checking Tesseract OCR installation..." -ForegroundColor Cyan
if (Test-Path "$TesseractDefaultPath\tesseract.exe") {
    Write-Host "Tesseract OCR is already installed at $TesseractDefaultPath." -ForegroundColor Green
} else {
    Write-Host "Tesseract OCR not found. Installing silently via winget..." -ForegroundColor Yellow
    try {
        # UB-Mannheim.TesseractOCR is the official community build package on Winget
        Start-Process winget -ArgumentList "install --id UB-Mannheim.TesseractOCR --silent --accept-source-agreements --accept-package-agreements" -Wait -NoNewWindow
        
        # Verify installation succeeded
        if (Test-Path "$TesseractDefaultPath\tesseract.exe") {
            Write-Host "Tesseract OCR successfully installed." -ForegroundColor Green
        } else {
            throw "Tesseract installation path not found after winget execution."
        }
    } catch {
        Write-Host "Failed to install Tesseract OCR automatically via winget." -ForegroundColor Red
        Write-Host "Please install it manually from: https://github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Yellow
        exit
    }
}

# Step 2: Download and install Khmer Language Pack
Write-Host "`n[2/6] Downloading Khmer language pack..." -ForegroundColor Cyan
$TessDataPath = "$TesseractDefaultPath\tessdata"
$KhmerDataFile = "$TessDataPath\khm.traineddata"

if (Test-Path $KhmerDataFile) {
    Write-Host "Khmer language pack (khm.traineddata) is already present." -ForegroundColor Green
} else {
    Write-Host "Downloading khm.traineddata from official repository..." -ForegroundColor Yellow
    try {
        # Ensure tessdata directory exists
        if (-not (Test-Path $TessDataPath)) {
            New-Item -ItemType Directory -Force -Path $TessDataPath | Out-Null
        }
        
        # Download the file
        Invoke-WebRequest -Uri $TessDataURL -OutFile $KhmerDataFile -UserAgent "Mozilla/5.0"
        Write-Host "Khmer language pack installed successfully at $KhmerDataFile." -ForegroundColor Green
    } catch {
        Write-Host "Failed to download Khmer language pack automatically: $_" -ForegroundColor Red
        Write-Host "Please download it manually from: $TessDataURL and place it in $TessDataPath" -ForegroundColor Yellow
        exit
    }
}

# Step 3: Check and Install Python 3.11 via Winget
Write-Host "`n[3/6] Checking Python installation..." -ForegroundColor Cyan
$PythonInstalled = $false
try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python 3\.") {
        Write-Host "Python is already installed: $pythonVersion" -ForegroundColor Green
        $PythonInstalled = $true
    }
} catch {}

if (-not $PythonInstalled) {
    Write-Host "Python 3 not found. Installing Python 3.11 silently via winget..." -ForegroundColor Yellow
    try {
        Start-Process winget -ArgumentList "install --id Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements" -Wait -NoNewWindow
        Write-Host "Python 3.11 installed. You may need to restart your terminal or computer for environment variables to update." -ForegroundColor Green
        # Refresh environment variables for the current session
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    } catch {
        Write-Host "Failed to install Python automatically via winget." -ForegroundColor Red
        Write-Host "Please install Python 3.11 manually from: https://www.python.org/downloads/" -ForegroundColor Yellow
        exit
    }
}

# Step 4: Deploy Application Files
Write-Host "`n[4/6] Setting up application directory..." -ForegroundColor Cyan
if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
}

# If running locally from the project directory, copy current files.
# Otherwise, we could download from a repository.
$CurrentScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path "$CurrentScriptDir\main.py") {
    Write-Host "Copying project files from current directory..." -ForegroundColor Yellow
    Copy-Item -Path "$CurrentScriptDir\*" -Destination $TargetDir -Recurse -Force -Exclude "venv", "logs", ".git"
} else {
    Write-Host "Downloading application source code..." -ForegroundColor Yellow
    $ZipPath = "$env:TEMP\khmer_ocr.zip"
    $TempExtractDir = "$env:TEMP\khmer_ocr_extracted"
    try {
        # Clean up any old temp extraction directory
        if (Test-Path $TempExtractDir) {
            Remove-Item $TempExtractDir -Recurse -Force | Out-Null
        }
        
        # Download the repository zip
        Invoke-WebRequest -Uri $RepoZipURL -OutFile $ZipPath -UserAgent "Mozilla/5.0"
        
        # Extract to a temp folder to handle the nested GitHub repository folder
        Expand-Archive -Path $ZipPath -DestinationPath $TempExtractDir -Force
        
        # Find the nested repository directory (usually named <repo>-<branch>)
        $ExtractedFolder = Get-ChildItem -Path $TempExtractDir -Directory | Select-Object -First 1
        if ($ExtractedFolder) {
            # Move contents directly into the target application directory
            Copy-Item -Path "$($ExtractedFolder.FullName)\*" -Destination $TargetDir -Recurse -Force
        } else {
            throw "No folder found inside the extracted ZIP."
        }
        
        # Clean up temporary zip and extraction folder
        Remove-Item $ZipPath -Force | Out-Null
        Remove-Item $TempExtractDir -Recurse -Force | Out-Null
    } catch {
        Write-Host "Could not fetch and extract source code automatically: $_" -ForegroundColor Red
        exit
    }
}
Write-Host "Application deployed to: $TargetDir" -ForegroundColor Green

# Step 5: Configure Python Virtual Environment
Write-Host "`n[5/6] Creating Python virtual environment..." -ForegroundColor Cyan
Set-Location $TargetDir
try {
    if (-not (Test-Path "$TargetDir\venv")) {
        Start-Process python -ArgumentList "-m venv venv" -Wait -NoNewWindow
    }
    Write-Host "Virtual environment configured." -ForegroundColor Green
    
    Write-Host "Installing Python dependencies (requirements.txt)..." -ForegroundColor Yellow
    Start-Process ".\venv\Scripts\python.exe" -ArgumentList "-m pip install --upgrade pip" -Wait -NoNewWindow
    Start-Process ".\venv\Scripts\pip.exe" -ArgumentList "install -r requirements.txt" -Wait -NoNewWindow
    Write-Host "Dependencies successfully installed." -ForegroundColor Green
    
    # Generate custom Windows ICO file during installation
    Write-Host "Generating custom Windows icon (logo.ico)..." -ForegroundColor Yellow
    Start-Process ".\venv\Scripts\python.exe" -ArgumentList "-c `"from PIL import Image; Image.open('logo.png').save('logo.ico', format='ICO')`"" -Wait -NoNewWindow
} catch {
    Write-Host "Failed to set up Python virtual environment or install dependencies: $_" -ForegroundColor Red
    exit
}

# Step 6: Create Desktop & Startup Shortcuts
Write-Host "`n[6/6] Creating application shortcuts..." -ForegroundColor Cyan
try {
    $WshShell = New-Object -ComObject WScript.Shell
    
    # Run target uses 'pythonw.exe' (windowless Python) so no console window is visible
    $TargetPath = "$TargetDir\venv\Scripts\pythonw.exe"
    $Arguments = "`"$TargetDir\main.py`""
    
    # 1. Desktop Shortcut
    $DesktopShortcutPath = "$env:USERPROFILE\Desktop\Khmer OCR.lnk"
    $Shortcut = $WshShell.CreateShortcut($DesktopShortcutPath)
    $Shortcut.TargetPath = $TargetPath
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $TargetDir
    $Shortcut.IconLocation = "$TargetDir\logo.ico" # Assign custom branded icon
    $Shortcut.Description = "Offline Khmer OCR Reader"
    $Shortcut.Save()
    
    # 2. Startup Shortcut (Runs automatically on boot)
    $StartupShortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Khmer OCR.lnk"
    $StartupShortcut = $WshShell.CreateShortcut($StartupShortcutPath)
    $StartupShortcut.TargetPath = $TargetPath
    $StartupShortcut.Arguments = $Arguments
    $StartupShortcut.WorkingDirectory = $TargetDir
    $StartupShortcut.IconLocation = "$TargetDir\logo.ico" # Assign custom branded icon
    $Shortcut.Description = "Offline Khmer OCR Reader Startup"
    $StartupShortcut.Save()
    
    Write-Host "Shortcuts created on Desktop and in Windows Startup folder." -ForegroundColor Green
} catch {
    Write-Host "Failed to create shortcuts: $_" -ForegroundColor Yellow
}

Write-Host "`n===============================================" -ForegroundColor Green
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "  You can run the app from your Desktop shortcut." -ForegroundColor Green
Write-Host "  Press Win + Shift + K to capture Khmer text." -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host "`nPress any key to exit..."
[void][System.Console]::ReadKey($true)
