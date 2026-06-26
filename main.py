import sys
import os
import logging
from PyQt6.QtCore import Qt, QObject, pyqtSlot, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QBrush, QColor, QFont, QAction
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox

# Register a custom Windows App User Model ID (AUMID)
# This forces Windows to group notifications under the application name rather than "Python"
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Khmer OCR")
    except Exception:
        pass

# Ensure the logs directory exists before configuring logging
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOG_DIR, "app.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger("KhmerOCR.Main")

# Import modular components
import config
from hotkey import HotkeyListener
from overlay import OverlayManager
from capture import capture_region
from ocr import OCRWorker
from updater import AutoUpdater
import pyperclip

class KhmerOCRApp(QObject):
    """
    Main application manager that coordinates the global hotkey,
    selection overlay, screen capture, OCR worker, and system tray.
    """
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        
        # 1. Create a system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self._create_stylish_icon())
        self.tray_icon.setToolTip("Offline Khmer OCR (Win + Shift + K)")
        
        # 2. Build the tray menu
        self.tray_menu = QMenu()
        
        self.capture_action = QAction("Capture Text (Win+Shift+K)", self)
        self.capture_action.triggered.connect(self.start_capture_flow)
        self.tray_menu.addAction(self.capture_action)
        
        self.help_action = QAction("How to Setup & Use", self)
        self.help_action.triggered.connect(self.show_help_dialog)
        self.tray_menu.addAction(self.help_action)
        
        self.update_action = QAction(f"Check for Updates (v{config.VERSION})", self)
        self.update_action.triggered.connect(self.check_for_updates_manually)
        self.tray_menu.addAction(self.update_action)
        
        self.tray_menu.addSeparator()
        
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.exit_application)
        self.tray_menu.addAction(self.exit_action)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        
        # 3. Initialize overlays and threads
        self.overlay_manager = OverlayManager()
        self.overlay_manager.selection_completed.connect(self.on_selection_completed)
        self.overlay_manager.selection_cancelled.connect(self.on_selection_cancelled)
        
        self.ocr_worker = None
        
        # 4. Start the background global hotkey listener
        self.hotkey_listener = HotkeyListener()
        self.hotkey_listener.triggered.connect(self.start_capture_flow)
        self.hotkey_listener.start()
        
        # Double click on tray icon also triggers capture
        self.tray_icon.activated.connect(self.on_tray_activated)
        
        logger.info("Application initialized and running in system tray.")
        self.show_tray_message(
            "Khmer OCR Running", 
            "Press Win + Shift + K to capture and OCR Khmer text offline."
        )
        
        # 5. Initialize and start the silent background auto-updater after a 5-second delay
        self.updater = AutoUpdater(os.path.dirname(os.path.abspath(__file__)))
        self.updater.update_ready.connect(self.on_update_ready)
        self.updater.update_error.connect(self.on_update_error)
        self.updater.no_update_needed.connect(self.on_no_update_needed)
        
        self.manual_update_check = False
        QTimer.singleShot(5000, self.updater.start)

    def _create_stylish_icon(self) -> QIcon:
        """Loads the custom designed logo if available; otherwise falls back to a generated icon."""
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        if os.path.exists(logo_path):
            logger.info(f"Loading custom logo from: {logo_path}")
            return QIcon(logo_path)
            
        logger.info("Custom logo.png not found. Falling back to generated icon.")
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw a beautiful rounded blue square
        painter.setBrush(QBrush(QColor(0, 120, 215))) # Premium Windows accent blue
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 64, 64, 16, 16)
        
        # Draw a sleek white letter 'K' for Khmer OCR
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Segoe UI", 36, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "K")
        painter.end()
        
        return QIcon(pixmap)

    def show_tray_message(self, title: str, message: str, icon=None):
        """Displays a Windows desktop notification from the system tray."""
        if icon is None:
            # Fallback to the custom stylish QIcon
            icon = self.tray_icon.icon()
        self.tray_icon.showMessage(title, message, icon, 3000)

    @pyqtSlot()
    def start_capture_flow(self):
        """Starts the screen region selection overlay."""
        logger.info("Starting screen selection flow.")
        # Ensure we don't open multiple overlay sets
        self.overlay_manager.start_selection()

    @pyqtSlot(QSystemTrayIcon.ActivationReason)
    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click or double click on tray triggers capture
            self.start_capture_flow()

    @pyqtSlot(int, int, int, int)
    def on_selection_completed(self, x, y, w, h):
        """Callback when the user finishes dragging the selection box."""
        logger.info(f"Overlay selection received: {x}, {y}, {w}, {h}. Starting capture and OCR.")
        try:
            # Capture the selected region using mss
            image = capture_region(x, y, w, h)
            
            # Start background OCR processing
            self.ocr_worker = OCRWorker(image)
            self.ocr_worker.finished.connect(self.on_ocr_success)
            self.ocr_worker.error.connect(self.on_ocr_error)
            self.ocr_worker.start()
            
            # Notify the user that processing has started
            self.show_tray_message("Processing...", "Recognizing Khmer text...")
            
        except Exception as e:
            logger.error(f"Error in capture flow: {e}")
            self.show_tray_message("Capture Error", f"Failed to capture screen: {str(e)}", QSystemTrayIcon.MessageIcon.Warning)

    @pyqtSlot()
    def on_selection_cancelled(self):
        logger.info("Screen selection cancelled by user.")

    @pyqtSlot(str)
    def on_ocr_success(self, text: str):
        """Callback when OCR successfully finishes."""
        if not text:
            logger.warning("OCR complete, but no text was recognized.")
            self.show_tray_message(
                "OCR Warning", 
                "No text recognized. Please ensure the captured area contains clear Khmer text.",
                QSystemTrayIcon.MessageIcon.Warning
            )
            return

        # Copy to clipboard
        pyperclip.copy(text)
        logger.info("Successfully copied recognized text to clipboard.")
        
        # Create a short preview for the tray notification
        preview = text[:60] + "..." if len(text) > 60 else text
        # Replace newlines with spaces for notification readability
        preview_clean = preview.replace("\n", " ")
        
        self.show_tray_message(
            "Copied to Clipboard!", 
            f"Preview: {preview_clean}"
        )

    @pyqtSlot(str)
    def on_ocr_error(self, error_message: str):
        """Callback when OCR fails."""
        logger.error(f"OCR failed: {error_message}")
        
        # Show a non-modal message box for errors to make sure the user sees details,
        # but don't block the main thread. A tray message is also shown.
        self.show_tray_message("OCR Error", "Failed to perform OCR. See details in the dialog.", QSystemTrayIcon.MessageIcon.Critical)
        
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("Khmer OCR Error")
        msg_box.setText("An error occurred during offline OCR processing.")
        msg_box.setInformativeText(error_message)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    @pyqtSlot()
    def show_help_dialog(self):
        """Shows application help and setup instructions."""
        help_text = (
            "<h3>Offline Khmer OCR App</h3>"
            "<p><b>How to use:</b></p>"
            "<ol>"
            "<li>Press <b>Win + Shift + K</b> (or click the tray icon).</li>"
            "<li>The screen will dim. Click and drag a rectangle over any Khmer text on your screen.</li>"
            "<li>Release the mouse to capture. The app will process the image offline and copy the text to your clipboard.</li>"
            "<li>Press <b>ESC</b> at any time to cancel.</li>"
            "</ol>"
            "<p><b>Prerequisites for Offline OCR:</b></p>"
            "<ul>"
            "<li><b>Tesseract OCR:</b> Must be installed on your system.</li>"
            "<li><b>Khmer Language Pack:</b> The file <code>khm.traineddata</code> must be placed in Tesseract's <code>tessdata</code> folder.</li>"
            "</ul>"
            "<p>Check the <code>README.md</code> in the project directory for step-by-step setup links and configuration details.</p>"
        )
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Setup & Usage Instructions")
        msg_box.setText(help_text)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    @pyqtSlot()
    def check_for_updates_manually(self):
        """Manually triggers an update check from the tray menu."""
        logger.info("Manual update check requested.")
        if self.updater.isRunning():
            self.show_tray_message("Checking...", "An update check is already in progress.")
            return
            
        self.manual_update_check = True
        self.show_tray_message("Checking for Updates", "Checking GitHub for newer versions...")
        self.updater.start()

    @pyqtSlot()
    def on_update_ready(self):
        """Callback when an update has been downloaded and applied in the background."""
        logger.info("Update ready. Triggering restart.")
        self.show_tray_message(
            "Update Installed!", 
            "The latest version has been downloaded. Restarting application to apply updates...",
            QSystemTrayIcon.MessageIcon.Information
        )
        # Wait 3 seconds for the user to read the message, then restart
        QTimer.singleShot(3000, self.restart_application)

    @pyqtSlot(str)
    def on_update_error(self, error_message: str):
        logger.error(f"Auto-update error: {error_message}")
        if self.manual_update_check:
            self.manual_update_check = False
            self.show_tray_message("Update Failed", "Failed to check for updates. See logs for details.", QSystemTrayIcon.MessageIcon.Warning)

    @pyqtSlot()
    def on_no_update_needed(self):
        logger.info("No update needed.")
        if self.manual_update_check:
            self.manual_update_check = False
            self.show_tray_message(
                "Up to Date", 
                f"You are running the latest version (v{config.VERSION}).",
                QSystemTrayIcon.MessageIcon.Information
            )

    def restart_application(self):
        """Cleanly restarts the application to load updated files."""
        logger.info("Restarting application...")
        self.hotkey_listener.stop()
        self.tray_icon.hide()
        # Restart the python process
        os.execv(sys.executable, [sys.executable] + sys.argv)

    @pyqtSlot()
    def exit_application(self):
        """Stops threads and quits the application cleanly."""
        logger.info("Exiting application...")
        # Stop the hotkey listener Win32 message loop thread
        self.hotkey_listener.stop()
        
        # Stop the updater if running
        if self.updater.isRunning():
            self.updater.terminate()
            self.updater.wait()
        
        # Hide the tray icon immediately to prevent it from lingering in the taskbar
        self.tray_icon.hide()
        
        # Quit the Qt Application
        self.app.quit()

def main():
    # Ensure High DPI scaling is handled correctly in PyQt6
    # This prevents coordinates mismatch on 4K/high-res screens
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
    # Automatically generate/update the Windows ICO file from logo.png on startup
    # If the PNG logo is newer than the ICO icon (or if the ICO is missing), it is regenerated
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(base_dir, "logo.png")
    ico_path = os.path.join(base_dir, "logo_v3.ico")
    if os.path.exists(logo_path):
        if not os.path.exists(ico_path) or os.path.getmtime(logo_path) > os.path.getmtime(ico_path):
            try:
                from PIL import Image as PILImage
                img = PILImage.open(logo_path)
                img.save(
                    ico_path, 
                    format="ICO", 
                    sizes=[(256, 256)]
                )
                # Programmatically notify the Windows Shell to clear and rebuild the icon cache globally
                if sys.platform == "win32":
                    import ctypes
                    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
            except Exception:
                pass
    
    app = QApplication(sys.argv)
    
    # Set application identity
    app.setApplicationName("Khmer OCR")
    app.setApplicationDisplayName("Khmer OCR")
    
    # Do not quit the app when the overlay window is closed
    app.setQuitOnLastWindowClosed(False)
    
    # Instantiate the application coordinator
    ocr_app = KhmerOCRApp(app)
    
    # Set app-level icon
    app.setWindowIcon(ocr_app.tray_icon.icon())
    
    # Start the Qt event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
