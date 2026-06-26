import os
import logging
from pathlib import Path

# Project Directories
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Application Versioning & Updates
VERSION = "1.2.0"
GITHUB_REPO = "OiiiSteav/khmer-ocr"

# Logging configuration
LOG_FILE = LOG_DIR / "app.log"
LOG_LEVEL = logging.INFO

# Tesseract Configuration
# Common installation paths for Tesseract on Windows and macOS
import sys

TESSERACT_SEARCH_PATHS = []
if sys.platform == "win32":
    TESSERACT_SEARCH_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
elif sys.platform == "darwin":  # macOS
    TESSERACT_SEARCH_PATHS = [
        "/opt/homebrew/bin/tesseract",  # Apple Silicon (M1/M2/M3)
        "/usr/local/bin/tesseract",    # Intel Macs
    ]

def get_tesseract_path() -> str:
    """Find the Tesseract executable path, prioritizing environment variable."""
    env_path = os.environ.get("TESSERACT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
        
    for path in TESSERACT_SEARCH_PATHS:
        if os.path.exists(path):
            return path
            
    # Default to standard Windows path if none found
    if sys.platform == "win32":
        return r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    else:
        return "tesseract"  # Rely on system PATH for Unix/macOS

TESSERACT_CMD = get_tesseract_path()
OCR_LANG = "khm"

# Hotkey Configuration (Win + Shift + K)
# Windows Modifiers:
# MOD_ALT = 0x0001
# MOD_CONTROL = 0x0002
# MOD_SHIFT = 0x0004
# MOD_WIN = 0x0008
HOTKEY_MODIFIERS = 0x0008 | 0x0004  # MOD_WIN | MOD_SHIFT
HOTKEY_VK = 0x4B                     # Virtual Key Code for 'K' (0x4B)
HOTKEY_ID = 1                        # Unique ID for the hotkey registration
