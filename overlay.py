import logging
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QPainter, QColor, QPen, QCursor, QFont, QGuiApplication
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger("KhmerOCR.Overlay")

class SelectionOverlay(QWidget):
    """
    A full-screen transparent overlay for a single monitor.
    Allows the user to drag-select a region.
    """
    # Signal emitted when a selection is made on this screen.
    # Emits global coordinates: (x, y, width, height)
    selection_completed = pyqtSignal(int, int, int, int)
    # Signal emitted when the user cancels the selection (e.g., via Esc)
    selection_cancelled = pyqtSignal()

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        
        # Configure window properties for a transparent, frameless, top-most window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Match the geometry of the specific screen
        self.setGeometry(screen.geometry())
        
        # Selection tracking state
        self.start_pos = None
        self.end_pos = None
        self.is_dragging = False
        
        # Set cursor to crosshair for selection feel
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        
        # Set window title for accessibility/debugging
        self.setWindowTitle(f"Khmer OCR Overlay - Screen {screen.name()}")

    def keyPressEvent(self, event):
        """Handle keyboard events. Cancel on Esc."""
        if event.key() == Qt.Key.Key_Escape:
            logger.info("Esc pressed. Cancelling selection.")
            self.selection_cancelled.emit()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Start the selection drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.position().toPoint()
            self.end_pos = self.start_pos
            self.is_dragging = True
            self.update()

    def mouseMoveEvent(self, event):
        """Update the selection box while dragging."""
        if self.is_dragging:
            self.end_pos = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        """Finish the selection and emit the coordinates."""
        if event.button() == Qt.MouseButton.LeftButton and self.is_dragging:
            self.is_dragging = False
            self.end_pos = event.position().toPoint()
            
            # Calculate local selection rectangle
            selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            
            # Prevent accidental tiny clicks
            if selection_rect.width() > 5 and selection_rect.height() > 5:
                # Get the device pixel ratio for the screen to handle DPI scaling correctly with mss
                dpr = self.screen.devicePixelRatio()
                
                # Get the physical origin of this screen
                phys_x, phys_y = get_screen_physical_origin(self.screen)
                
                # Convert to global physical coordinates
                global_x = int(phys_x + selection_rect.x() * dpr)
                global_y = int(phys_y + selection_rect.y() * dpr)
                global_w = int(selection_rect.width() * dpr)
                global_h = int(selection_rect.height() * dpr)
                
                logger.info(f"Selection completed: local={selection_rect}, global_physical=({global_x}, {global_y}, {global_w}, {global_h}), dpr={dpr}")
                self.selection_completed.emit(global_x, global_y, global_w, global_h)
            else:
                logger.info("Selection too small, treating as cancel.")
                self.selection_cancelled.emit()
                
            self.start_pos = None
            self.end_pos = None

    def paintEvent(self, event):
        """Draw the dimmed screen and the clear selection box."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 1. Fill the screen with a semi-transparent dark overlay (dimmed screen)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 140))
        
        # 2. Draw helper instruction text near the top center of the screen
        painter.setPen(QColor(255, 255, 255, 220))
        font = QFont("Segoe UI", 13, QFont.Weight.Medium)
        painter.setFont(font)
        instruction_text = "Drag a rectangle to capture Khmer text | ESC to cancel"
        text_rect = painter.fontMetrics().boundingRect(instruction_text)
        
        # Center the text at the top
        text_x = (self.width() - text_rect.width()) // 2
        text_y = 40
        painter.drawText(text_x, text_y, instruction_text)
        
        # 3. If the user is selecting a region, carve out the selection box and style it
        if self.start_pos and self.end_pos:
            selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            
            if not selection_rect.isEmpty():
                # Clear the selection area (reveals the bright screen underneath)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.fillRect(selection_rect, Qt.GlobalColor.transparent)
                
                # Reset composition mode to normal to draw the border and size info
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                
                # Draw a sleek premium blue border around the selection
                border_color = QColor(0, 120, 215) # Modern accent blue
                pen = QPen(border_color, 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.drawRect(selection_rect)
                
                # Draw the selection dimensions in a small tag below the bottom-right corner
                size_text = f"{selection_rect.width()} x {selection_rect.height()}"
                painter.setFont(QFont("Segoe UI", 9))
                painter.setPen(QColor(255, 255, 255, 255))
                
                # Draw small background tag for dimensions text
                metrics = painter.fontMetrics()
                tag_w = metrics.horizontalAdvance(size_text) + 10
                tag_h = metrics.height() + 4
                tag_x = selection_rect.right() - tag_w
                tag_y = selection_rect.bottom() + 5
                
                # Ensure tag stays within screen boundaries
                if tag_y + tag_h > self.height():
                    tag_y = selection_rect.top() - tag_h - 5
                if tag_x < 0:
                    tag_x = 0
                    
                painter.fillRect(QRect(tag_x, tag_y, tag_w, tag_h), QColor(0, 120, 215, 220))
                painter.drawText(tag_x + 5, tag_y + metrics.ascent() + 2, size_text)


class OverlayManager(QObject):
    """
    Coordinates selection overlays across all connected monitors.
    """
    # Emitted when a selection is completed on any screen
    selection_completed = pyqtSignal(int, int, int, int)
    # Emitted when selection is cancelled
    selection_cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.overlays = []

    def start_selection(self):
        """Spawn a selection overlay on every connected screen."""
        self.close_all()
        
        screens = QGuiApplication.screens()
        logger.info(f"Spawning selection overlays across {len(screens)} screen(s).")
        
        for screen in screens:
            overlay = SelectionOverlay(screen)
            overlay.selection_completed.connect(self._on_selection_completed)
            overlay.selection_cancelled.connect(self._on_selection_cancelled)
            self.overlays.append(overlay)
            overlay.show()
            # Bring to front and activate
            overlay.raise_()
            overlay.activateWindow()

    def _on_selection_completed(self, x, y, w, h):
        self.close_all()
        self.selection_completed.emit(x, y, w, h)

    def _on_selection_cancelled(self):
        self.close_all()
        self.selection_cancelled.emit()

    def close_all(self):
        """Close and destroy all active overlays."""
        if self.overlays:
            logger.info("Closing all active overlays.")
            for overlay in self.overlays:
                overlay.close()
                overlay.deleteLater()
            self.overlays.clear()


def get_screen_physical_origin(screen) -> tuple[int, int]:
    """
    Finds the physical origin (left, top) of the given QScreen by matching it
    with the monitors detected by mss.
    """
    import mss
    from PyQt6.QtGui import QGuiApplication
    
    try:
        qt_screens = QGuiApplication.screens()
        with mss.mss() as sct:
            mss_monitors = sct.monitors[1:] # Exclude virtual monitor at index 0
            
        if len(qt_screens) == 1 or len(mss_monitors) == 1:
            if mss_monitors:
                return mss_monitors[0]['left'], mss_monitors[0]['top']
            return 0, 0

        # Group by physical size
        qt_groups = {}
        for s in qt_screens:
            dpr = s.devicePixelRatio()
            w = round(s.geometry().width() * dpr)
            h = round(s.geometry().height() * dpr)
            qt_groups.setdefault((w, h), []).append(s)
            
        mss_groups = {}
        for m in mss_monitors:
            w = m['width']
            h = m['height']
            mss_groups.setdefault((w, h), []).append(m)
            
        target_dpr = screen.devicePixelRatio()
        target_w = round(screen.geometry().width() * target_dpr)
        target_h = round(screen.geometry().height() * target_dpr)
        
        group_key = (target_w, target_h)
        if group_key in qt_groups and group_key in mss_groups:
            s_list = qt_groups[group_key]
            m_list = mss_groups[group_key]
            
            # Sort consistently by geometry to pair them up correctly
            s_list.sort(key=lambda s: (s.geometry().x(), s.geometry().y()))
            m_list.sort(key=lambda m: (m['left'], m['top']))
            
            if screen in s_list:
                idx = s_list.index(screen)
                if idx < len(m_list):
                    return m_list[idx]['left'], m_list[idx]['top']
    except Exception as e:
        logger.warning(f"Error matching QScreen to mss monitor: {e}")
        
    # Fallback
    target_dpr = screen.devicePixelRatio()
    return int(screen.geometry().x() * target_dpr), int(screen.geometry().y() * target_dpr)
