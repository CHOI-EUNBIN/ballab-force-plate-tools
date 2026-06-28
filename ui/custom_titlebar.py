"""Single-row custom title bar that merges the app menu with the window
controls, plus the Windows native glue (resize / Aero snap / maximize / drop
shadow) needed to make a frameless window still feel native.

Layout:  [icon]  [Analyze  Statistics  …]  ……drag area……  [min] [max] [close]

On Windows the window keeps a real resizable frame (WS_THICKFRAME) and DWM
shadow; only the OS caption is removed (via WM_NCCALCSIZE) so our one-row bar
takes its place. Dragging uses Qt's startSystemMove() so Aero snap works.
On other platforms it degrades to a plain frameless window with manual move.
"""
import sys

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QIcon, QPainter, QPen, QColor
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QLabel

TITLEBAR_HEIGHT = 38
_BTN_W = 46


class WindowButton(QToolButton):
    """A min / max / close button whose glyph is painted (so it tints with the
    theme) and whose hover background comes from the stylesheet."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind            # "min" | "max" | "close"
        self._maximized = False
        self._glyph = QColor("#E8EDF4")
        self.setFixedSize(_BTN_W, TITLEBAR_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("win-close" if kind == "close" else "win-btn")

    def set_glyph_color(self, color: QColor):
        self._glyph = color
        self.update()

    def set_maximized(self, maximized: bool):
        if self._maximized != maximized:
            self._maximized = maximized
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)  # hover/pressed background from the stylesheet
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Close uses a light glyph on its red hover; keep it white when hovered.
        glyph = self._glyph
        if self._kind == "close" and self.underMouse():
            glyph = QColor("#FFFFFF")
        pen = QPen(glyph)
        pen.setWidthF(1.2)
        p.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        r = 5  # half glyph size
        if self._kind == "min":
            p.drawLine(int(cx - r), int(cy), int(cx + r), int(cy))
        elif self._kind == "max":
            if self._maximized:
                # restore: a front square plus a back square peeking top-right
                p.drawRect(int(cx - r), int(cy - r + 2), 2 * r - 2, 2 * r - 2)
                p.drawLine(int(cx - r + 2), int(cy - r), int(cx + r), int(cy - r))
                p.drawLine(int(cx + r), int(cy - r), int(cx + r), int(cy + r - 2))
            else:
                p.drawRect(int(cx - r), int(cy - r), 2 * r, 2 * r)
        else:  # close
            p.drawLine(int(cx - r), int(cy - r), int(cx + r), int(cy + r))
            p.drawLine(int(cx + r), int(cy - r), int(cx - r), int(cy + r))
        p.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class TitleBar(QWidget):
    """The visible one-row bar. Holds the app icon, the menu bar and the window
    buttons. Empty regions drag the window; double-click toggles maximize."""

    def __init__(self, window, menubar, icon_path: str):
        super().__init__(window)
        self._win = window
        self.setObjectName("custom-titlebar")
        self.setFixedHeight(TITLEBAR_HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 0, 0)
        lay.setSpacing(8)

        self._icon = QLabel(self)
        self._icon.setPixmap(QIcon(icon_path).pixmap(18, 18))
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self.menubar = menubar
        self.menubar.setObjectName("titlebar-menu")
        lay.addWidget(self.menubar, 0, Qt.AlignmentFlag.AlignVCenter)

        lay.addStretch(1)

        self.btn_min = WindowButton("min", self)
        self.btn_max = WindowButton("max", self)
        self.btn_close = WindowButton("close", self)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(window.close)

    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def sync_maximized(self):
        self.btn_max.set_maximized(self._win.isMaximized())

    def apply_theme(self, pal: dict):
        self.setStyleSheet(f"""
            QWidget#custom-titlebar {{
                background: {pal['BG_PANEL']};
                border-bottom: 1px solid {pal['BORDER']};
            }}
            QMenuBar#titlebar-menu {{
                background: transparent;
                border: none;
                padding: 0px;
                color: {pal['TEXT_SECONDARY']};
            }}
            QMenuBar#titlebar-menu::item {{
                background: transparent;
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QMenuBar#titlebar-menu::item:selected {{
                background: {pal['BG_INPUT']};
                color: {pal['TEXT_PRIMARY']};
            }}
            QMenuBar#titlebar-menu::item:checked {{
                color: {pal['ACCENT_TEAL']};
                font-weight: 700;
            }}
            QToolButton#win-btn, QToolButton#win-close {{
                background: transparent;
                border: none;
            }}
            QToolButton#win-btn:hover {{ background: {pal['BG_HOVER']}; }}
            QToolButton#win-close:hover {{ background: {pal['ACCENT_RED']}; }}
        """)
        glyph = QColor(pal["TEXT_PRIMARY"])
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.set_glyph_color(glyph)

    # --- dragging / double-click on the empty part of the bar ---
    def _on_chrome(self, pos) -> bool:
        """True if the press is on draggable chrome (not the menu / buttons)."""
        child = self.childAt(pos)
        if child is None:
            return True
        return child is self._icon

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_chrome(event.position().toPoint()):
            handle = self._win.windowHandle()
            if handle is not None and hasattr(handle, "startSystemMove"):
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_chrome(event.position().toPoint()):
            self._toggle_max()
            return
        super().mouseDoubleClickEvent(event)


# ===========================================================================
# Windows native glue: frameless window that keeps resize / snap / shadow.
# ===========================================================================

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _WM_NCCALCSIZE = 0x0083
    _WM_NCHITTEST = 0x0084
    _WM_GETMINMAXINFO = 0x0024

    _HTCLIENT = 1
    _HTLEFT, _HTRIGHT, _HTTOP, _HTTOPLEFT, _HTTOPRIGHT = 10, 11, 12, 13, 14
    _HTBOTTOM, _HTBOTTOMLEFT, _HTBOTTOMRIGHT = 15, 16, 17

    _GWL_STYLE = -16
    _WS_THICKFRAME = 0x00040000
    _WS_CAPTION = 0x00C00000
    _WS_MAXIMIZEBOX = 0x00010000
    _WS_MINIMIZEBOX = 0x00020000

    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_NOZORDER = 0x0004
    _SWP_FRAMECHANGED = 0x0020

    _SM_CXSIZEFRAME = 32
    _SM_CXPADDEDBORDER = 92

    class _MARGINS(ctypes.Structure):
        _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _MINMAXINFO(ctypes.Structure):
        _fields_ = [("ptReserved", _POINT), ("ptMaxSize", _POINT),
                    ("ptMaxPosition", _POINT), ("ptMinTrackSize", _POINT),
                    ("ptMaxTrackSize", _POINT)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    _user32 = ctypes.windll.user32
    _dwmapi = ctypes.windll.dwmapi

    def _resize_border(hwnd) -> int:
        return (_user32.GetSystemMetrics(_SM_CXSIZEFRAME)
                + _user32.GetSystemMetrics(_SM_CXPADDEDBORDER))

    def enable_frameless(window):
        """Re-add a native resizable frame + shadow to a Qt frameless window."""
        hwnd = int(window.winId())
        style = _user32.GetWindowLongW(hwnd, _GWL_STYLE)
        _user32.SetWindowLongW(
            hwnd, _GWL_STYLE,
            style | _WS_THICKFRAME | _WS_CAPTION
            | _WS_MAXIMIZEBOX | _WS_MINIMIZEBOX)
        _user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED)
        # Drop shadow (sheet-of-glass margins; our opaque widgets cover it).
        margins = _MARGINS(-1, -1, -1, -1)
        _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

    def handle_native_event(window, message):
        """Return (handled, result) for nativeEvent, or None to fall through."""
        msg = ctypes.wintypes.MSG.from_address(int(message))
        m = msg.message
        if m == _WM_NCCALCSIZE:
            if msg.wParam:
                if window.isMaximized():
                    rect = wintypes.RECT.from_address(msg.lParam)
                    t = _resize_border(msg.hwnd)
                    rect.left += t
                    rect.top += t
                    rect.right -= t
                    rect.bottom -= t
                return True, 0
            return None
        if m == _WM_NCHITTEST:
            if window.isMaximized() or window.isFullScreen():
                return None
            x = msg.lParam & 0xFFFF
            if x >= 0x8000:
                x -= 0x10000
            y = (msg.lParam >> 16) & 0xFFFF
            if y >= 0x8000:
                y -= 0x10000
            pos = window.mapFromGlobal(QPoint(x, y))
            bw = 6
            w, h = window.width(), window.height()
            left, right = pos.x() < bw, pos.x() >= w - bw
            top, bottom = pos.y() < bw, pos.y() >= h - bw
            if top and left:
                return True, _HTTOPLEFT
            if top and right:
                return True, _HTTOPRIGHT
            if bottom and left:
                return True, _HTBOTTOMLEFT
            if bottom and right:
                return True, _HTBOTTOMRIGHT
            if left:
                return True, _HTLEFT
            if right:
                return True, _HTRIGHT
            if top:
                return True, _HTTOP
            if bottom:
                return True, _HTBOTTOM
            return None
        if m == _WM_GETMINMAXINFO:
            monitor = _user32.MonitorFromWindow(msg.hwnd, 2)  # NEAREST
            if monitor:
                info = _MONITORINFO()
                info.cbSize = ctypes.sizeof(_MONITORINFO)
                _user32.GetMonitorInfoW(monitor, ctypes.byref(info))
                work, full = info.rcWork, info.rcMonitor
                mmi = _MINMAXINFO.from_address(msg.lParam)
                mmi.ptMaxPosition.x = work.left - full.left
                mmi.ptMaxPosition.y = work.top - full.top
                mmi.ptMaxSize.x = work.right - work.left
                mmi.ptMaxSize.y = work.bottom - work.top
                mmi.ptMaxTrackSize.x = work.right - work.left
                mmi.ptMaxTrackSize.y = work.bottom - work.top
                return True, 0
            return None
        return None

else:  # non-Windows fallback
    def enable_frameless(window):
        pass

    def handle_native_event(window, message):
        return None
