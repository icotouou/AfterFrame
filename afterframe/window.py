import ctypes
import math
import os
from typing import List, Tuple

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    Property,
    QElapsedTimer,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import (
    QPropertyAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QSequentialAnimationGroup,
)

from .constants import (
    APP_NAME,
    APP_VERSION_SHORT,
    BACKGROUND_ALPHA,
    BACKGROUND_COLOR,
    BAR_COLOR,
    BAR_HEIGHT,
    BAR_LEFT_PADDING,
    BAR_WIDTH,
    BORDER_COLOR,
    CHROME_FLAT_DURATION,
    CHROME_WASH_HIDES_FROST_ALPHA,
    CLOSE_HOVER_COLOR,
    EXPAND_DURATION,
    EXPAND_EASING,
    FLASH_COUNT,
    FLASH_DURATION,
    FROSTED_CHROME_FLAGS,
    FROSTED_CHROME_STATE,
    FROSTED_CHROME_TINT,
    HEADING_WEIGHT,
    INITIAL_SIZE,
    MAIN_WINDOW_HEIGHT,
    MAIN_WINDOW_MIN_HEIGHT,
    MAIN_WINDOW_MIN_WIDTH,
    MAIN_WINDOW_RESIZE_BOUNCE,
    MAIN_WINDOW_RESIZE_OVERSHOOT,
    MAIN_WINDOW_RESIZE_SQUEEZE,
    MAIN_WINDOW_WIDTH,
    MINIMIZE_SHUTDOWN_DURATION,
    MOVE_DURATION,
    MOVE_EASING,
    RESIZE_BORDER,
    RESIZE_CORNER,
    RESIZE_OPEN_VELOCITY_GAIN,
    RESIZE_OPEN_VELOCITY_MAX,
    RESIZE_RELEASE_VELOCITY_GAIN,
    RESIZE_SPRING_DAMPING,
    RESIZE_SPRING_STIFFNESS,
    RESIZE_SQUEEZE_MAX,
    RESIZE_SQUEEZE_POWER,
    RESIZE_SQUEEZE_SOFTNESS,
    RESIZE_VELOCITY_STALE_MS,
    RESIZE_VELOCITY_TAU_MS,
    RESTORE_SCAN_DURATION,
    SETTINGS_KEY_FOLDER,
    SETTINGS_KEY_VISUALIZER,
    SETTINGS_KEY_WIPE,
    ICON_FONT_FAMILY,
    TEXT_COLOR,
    TEXT_FONT_FAMILY,
    TEXT_FONT_SIZE,
    TEXT_REVEAL_BAND,
    TEXT_SECONDARY_COLOR,
    TEXT_Y_OFFSET,
    TITLE_BAR_HEIGHT,
    TRAIL_COUNT,
    TRAIL_MAX_AGE_MS,
    TRAIL_SAMPLE_INTERVAL_MS,
    TRANSITION_TO_MAIN_DURATION,
    TRANSITION_TO_MAIN_EASING,
    WINDOW_CORNER_RADIUS,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    WIPE_DURATION,
)




from .dashboard import SystemDashboard
from .page_stack import PageStack, Sidebar
from .theme import ThemeAnimator, rgba, theme_for_page
from .settings_page import SettingsPage, read_frosted_level, read_lyrics_align
from .settings_store import settings
from .toy_page import ToyPage


def _read_bool_setting(key: str, default: bool) -> bool:
    """Read a boolean preference stored with QSettings."""
    value = settings().value(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _read_str_setting(key: str, default: str = "") -> str:
    """Read a string preference stored with QSettings."""
    return str(settings().value(key, default) or "")


class CustomTitleBar(QWidget):
    """Custom title bar for the frameless main window."""

    def __init__(self, parent: QWidget, window: QWidget) -> None:
        super().__init__(parent)
        self._window = window

        self.setFixedHeight(TITLE_BAR_HEIGHT)
        # Page-following chrome palette, cross-faded on page switches.
        self._theme = theme_for_page(0)
        self._themer = ThemeAnimator(self._apply_theme, self)
        self._setup_ui()
        self._apply_theme(self._theme)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        # Explicit spacers (spacing 0) so the gaps are exactly what is asked:
        # a small one either side of the divider, a wider one to minimize.
        layout.setSpacing(0)

        self.icon_label = QLabel("◆")
        self.title_label = QLabel(APP_NAME)

        layout.addWidget(self.icon_label)
        layout.addSpacing(6)
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.min_btn = self._create_control_button("−", self._minimize)
        self.close_btn = self._create_control_button("✕", self._close)
        self.close_btn.setObjectName("close")

        # Settings sits to the left of minimize: [settings] 4px | 14px [min][close]
        self.settings_btn = self._create_control_button("⚙", self._open_settings)
        self._settings_active = False
        layout.addWidget(self.settings_btn)
        layout.addSpacing(4)

        self.divider = QFrame(self)
        self.divider.setFixedWidth(1)
        self.divider.setFixedHeight(16)
        layout.addWidget(self.divider, 0, Qt.AlignVCenter)
        layout.addSpacing(14)

        layout.addWidget(self.min_btn)
        layout.addSpacing(6)
        layout.addWidget(self.close_btn)

    def _create_control_button(self, text: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(32, 26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(callback)
        return btn

    def set_theme(self, theme: dict, animate: bool = True) -> None:
        """Adopt the palette of the page that is now active."""
        self._themer.to(theme, animate=animate)

    def _apply_theme(self, theme: dict) -> None:
        self._theme = theme
        self.icon_label.setStyleSheet(
            f"color: {rgba(theme['icon_active'])}; font-size: 12px;"
        )
        self.title_label.setStyleSheet(
            f"color: {rgba(theme['text'])}; font-size: 13px; font-weight: 500;"
        )
        # The settings icon turns brand green while its page is open.
        settings_color = (
            theme["icon_active"] if self._settings_active else theme["control_idle"]
        )
        self.settings_btn.setStyleSheet(
            self._control_button_style(theme, icon_color=settings_color)
        )
        self.min_btn.setStyleSheet(self._control_button_style(theme))
        self.close_btn.setStyleSheet(self._control_button_style(theme))

        divider = QColor(theme["chrome_border"])
        divider.setAlpha(min(255, divider.alpha() + 46))
        self.divider.setStyleSheet(f"background: {rgba(divider)}; border: none;")
        self.update()

    def _control_button_style(self, theme: dict, icon_color: QColor = None) -> str:
        idle = icon_color if icon_color is not None else theme["control_idle"]
        return f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {rgba(idle)};
                font-family: "{ICON_FONT_FAMILY}";
                font-size: 13px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {rgba(theme['control_hover_bg'])};
                color: {rgba(theme['control_hover_text'])};
            }}
            QPushButton#close:hover {{
                background: {self._rgb_hex(CLOSE_HOVER_COLOR)};
                color: white;
            }}
        """

    def set_settings_active(self, active: bool) -> None:
        """Highlight the settings icon while the settings page is shown."""
        if active == self._settings_active:
            return
        self._settings_active = active
        self._apply_theme(self._theme)

    def _open_settings(self) -> None:
        self._window.open_settings_page()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._theme["chrome_bg"])
        painter.setPen(QPen(self._theme["chrome_border"], 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

    @staticmethod
    def _rgb_hex(color: Tuple[int, ...]) -> str:
        return "#" + "".join(f"{c:02x}" for c in color[:3])

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._window.start_spring_drag(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() == Qt.LeftButton:
            self._window.update_spring_drag(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._window.stop_spring_drag()

    def _minimize(self) -> None:
        self._window.animate_minimize()

    def _close(self) -> None:
        self._window.animate_close()
class _CloseAnimator(QWidget):
    """Fullscreen overlay that plays the close animation.

    A green bar flies in from the right, sweeps across the captured window,
    erasing it column by column, then stretches and flies off to the left.
    """

    finished = Signal()

    def __init__(
        self,
        screen_geo: QRect,
        window_geo: QRect,
        pixmap: QPixmap,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._screen_geo = screen_geo
        self._window_geo = window_geo
        self._pixmap = pixmap

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setGeometry(screen_geo)

        self._bar_leading = 0.0
        self._bar_trailing = 0.0
        self._bar_height = 0.0

        # Trail of recent bar states for a motion-blur / afterimage effect.
        self._trail: list[tuple[float, float, float, int]] = []
        self._trail_elapsed = QElapsedTimer()
        self._trail_elapsed.start()

        self._setup_animation()

    @Property(float)
    def bar_leading(self) -> float:
        return self._bar_leading

    @bar_leading.setter
    def bar_leading(self, value: float) -> None:
        self._bar_leading = value
        self.update()

    @Property(float)
    def bar_trailing(self) -> float:
        return self._bar_trailing

    @bar_trailing.setter
    def bar_trailing(self, value: float) -> None:
        self._bar_trailing = value
        self.update()

    @Property(float)
    def bar_height(self) -> float:
        return self._bar_height

    @bar_height.setter
    def bar_height(self, value: float) -> None:
        self._bar_height = value
        self.update()

    def _setup_animation(self) -> None:
        win_w = self._window_geo.width()
        win_h = self._window_geo.height()
        bar_width = 18  # wider sweep bar

        # Phase 1: approach from the right edge, tall bar shrinks to window height + 24.
        start_height = win_h * 1.25
        attach_height = win_h + 24

        start_leading = float(self._screen_geo.right() + 80)
        start_trailing = start_leading - 40.0
        attach_leading = float(self._window_geo.right())
        attach_trailing = attach_leading - bar_width

        self._bar_leading = start_leading
        self._bar_trailing = start_trailing
        self._bar_height = start_height

        self._group = QSequentialAnimationGroup(self)

        phase1 = QParallelAnimationGroup(self)
        a1_leading = QPropertyAnimation(self, b"bar_leading")
        a1_leading.setDuration(360)
        a1_leading.setStartValue(start_leading)
        a1_leading.setEndValue(attach_leading)
        a1_leading.setEasingCurve(QEasingCurve.OutBack)

        a1_trailing = QPropertyAnimation(self, b"bar_trailing")
        a1_trailing.setDuration(360)
        a1_trailing.setStartValue(start_trailing)
        a1_trailing.setEndValue(attach_trailing)
        a1_trailing.setEasingCurve(QEasingCurve.OutBack)

        a1_height = QPropertyAnimation(self, b"bar_height")
        a1_height.setDuration(360)
        a1_height.setStartValue(start_height)
        a1_height.setEndValue(attach_height)
        a1_height.setEasingCurve(QEasingCurve.OutBack)

        phase1.addAnimation(a1_leading)
        phase1.addAnimation(a1_trailing)
        phase1.addAnimation(a1_height)
        self._group.addAnimation(phase1)

        # Phase 2: sweep left across the window, erasing it.
        phase2 = QParallelAnimationGroup(self)
        a2_leading = QPropertyAnimation(self, b"bar_leading")
        a2_leading.setDuration(520)
        a2_leading.setStartValue(attach_leading)
        a2_leading.setEndValue(float(self._window_geo.left()))
        a2_leading.setEasingCurve(QEasingCurve.InOutCubic)

        a2_trailing = QPropertyAnimation(self, b"bar_trailing")
        a2_trailing.setDuration(520)
        a2_trailing.setStartValue(attach_trailing)
        a2_trailing.setEndValue(float(self._window_geo.left() - bar_width))
        a2_trailing.setEasingCurve(QEasingCurve.InOutCubic)

        phase2.addAnimation(a2_leading)
        phase2.addAnimation(a2_trailing)
        self._group.addAnimation(phase2)

        # Phase 3: the bar is pulled left and stretches before flying off.
        phase3 = QParallelAnimationGroup(self)
        stretch_leading_end = float(self._screen_geo.left() - 60)
        stretch_trailing_end = float(
            self._screen_geo.left() - max(120, int(win_w * 0.45))
        )

        a3_leading = QPropertyAnimation(self, b"bar_leading")
        a3_leading.setDuration(480)
        a3_leading.setStartValue(float(self._window_geo.left()))
        a3_leading.setEndValue(stretch_leading_end)
        a3_leading.setEasingCurve(QEasingCurve.OutQuint)

        a3_trailing = QPropertyAnimation(self, b"bar_trailing")
        a3_trailing.setDuration(480)
        a3_trailing.setStartValue(float(self._window_geo.left() - bar_width))
        a3_trailing.setEndValue(stretch_trailing_end)
        a3_trailing.setEasingCurve(QEasingCurve.OutBack)

        phase3.addAnimation(a3_leading)
        phase3.addAnimation(a3_trailing)
        self._group.addAnimation(phase3)

        self._group.finished.connect(self.finished.emit)
        self._group.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        offset = self._screen_geo.topLeft()
        win_local = self._window_geo.translated(-offset)

        # Draw the captured window only to the left of the leading bar edge.
        leading_local = self._bar_leading - offset.x()
        visible_w = min(leading_local - win_local.left(), win_local.width())
        if visible_w > 0:
            clip = QRectF(
                win_local.left(),
                win_local.top(),
                visible_w,
                win_local.height(),
            )
            painter.setClipRect(clip)
            painter.drawPixmap(
                QRectF(win_local),
                self._pixmap,
                QRectF(self._pixmap.rect()),
            )
            painter.setClipping(False)

        # Sample the current bar state for the trailing afterimage.
        now = self._trail_elapsed.elapsed()
        self._trail.append(
            (self._bar_trailing, self._bar_leading, self._bar_height, now)
        )
        cutoff = now - 420
        self._trail = [s for s in self._trail if s[3] > cutoff]
        if len(self._trail) > 25:
            self._trail = self._trail[-25:]

        # Draw fading trail ghosts behind the current bar.
        for trailing, leading, height, t in self._trail:
            age = now - t
            progress = 1.0 - (age / 420)
            progress = max(0.0, min(1.0, progress))
            if progress <= 0.01:
                continue
            opacity = progress ** 1.8
            ghost_alpha = int(200 * opacity)
            ghost_color = QColor(*BAR_COLOR, ghost_alpha)

            bar_left_local = trailing - offset.x()
            bar_width = leading - trailing
            bar_top_local = (
                self._window_geo.center().y() - height / 2 - offset.y()
            )
            painter.fillRect(
                QRectF(bar_left_local, bar_top_local, bar_width, height),
                ghost_color,
            )

        # Draw the green bar itself.
        bar_left_local = self._bar_trailing - offset.x()
        bar_width = self._bar_leading - self._bar_trailing
        bar_top_local = (
            self._window_geo.center().y() - self._bar_height / 2 - offset.y()
        )
        painter.fillRect(
            QRectF(bar_left_local, bar_top_local, bar_width, self._bar_height),
            QColor(*BAR_COLOR),
        )


class _MinimizeAnimator(QWidget):
    """Top-level overlay that plays a CRT shutdown collapse."""

    finished = Signal()

    def __init__(
        self,
        window_geo: QRect,
        pixmap: QPixmap,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._window_geo = window_geo
        self._pixmap = pixmap

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(window_geo)

        self._scan_height = float(window_geo.height())
        self._setup_animation()

    @Property(float)
    def scan_height(self) -> float:
        return self._scan_height

    @scan_height.setter
    def scan_height(self, value: float) -> None:
        self._scan_height = max(2.0, value)
        self.update()

    def _setup_animation(self) -> None:
        anim = QPropertyAnimation(self, b"scan_height", self)
        anim.setDuration(MINIMIZE_SHUTDOWN_DURATION)
        anim.setStartValue(float(self._window_geo.height()))
        anim.setEndValue(2.0)
        anim.setEasingCurve(QEasingCurve.InQuint)
        anim.finished.connect(self.finished.emit)
        anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        scan_h = self._scan_height
        band_top = (h - scan_h) / 2.0

        # Only the center content band is drawn; the areas already scanned
        # over are left transparent so the desktop shows through.

        # Still-visible content band in the center.
        clip = QRectF(0.0, band_top, w, scan_h)
        painter.setClipRect(clip)
        painter.drawPixmap(
            QRectF(0.0, 0.0, w, h),
            self._pixmap,
            QRectF(self._pixmap.rect()),
        )
        painter.setClipping(False)


class _RestoreAnimator(QWidget):
    """Top-level overlay that reveals the window like an old CRT powering on.

    A white, tapered, inverted line appears across the screen, then expands
    vertically to reveal the captured window content inside the window rect.
    """

    finished = Signal()

    def __init__(
        self,
        screen_geo: QRect,
        window_geo: QRect,
        pixmap: QPixmap,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._screen_geo = screen_geo
        self._window_geo = window_geo
        self._pixmap = pixmap

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(screen_geo)

        self._scan_height = 2.0
        self._setup_animation()

    @Property(float)
    def scan_height(self) -> float:
        return self._scan_height

    @scan_height.setter
    def scan_height(self, value: float) -> None:
        self._scan_height = max(2.0, value)
        self.update()

    def _setup_animation(self) -> None:
        anim = QPropertyAnimation(self, b"scan_height", self)
        anim.setDuration(RESTORE_SCAN_DURATION)
        anim.setStartValue(2.0)
        anim.setEndValue(float(self._window_geo.height()))
        anim.setEasingCurve(QEasingCurve.OutQuint)
        anim.finished.connect(self.finished.emit)
        anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        offset = self._screen_geo.topLeft()
        win_local = self._window_geo.translated(-offset)
        win_cx = win_local.center().x()
        win_cy = win_local.center().y()
        win_w = float(win_local.width())
        win_h = float(win_local.height())

        scan_h = self._scan_height
        band_top = win_cy - scan_h / 2.0
        band_bottom = band_top + scan_h

        # Reveal the captured window only inside the expanding horizontal band.
        clip = QRectF(win_local.left(), band_top, win_w, scan_h)
        painter.setClipRect(clip)
        painter.drawPixmap(
            QRectF(win_local),
            self._pixmap,
            QRectF(self._pixmap.rect()),
        )
        painter.setClipping(False)


class _WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("hwndInsertAfter", ctypes.c_void_p),
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
        ("cx", ctypes.c_long),
        ("cy", ctypes.c_long),
        ("flags", ctypes.c_uint),
    ]


class _ACCENT_POLICY(ctypes.Structure):
    """WCA_ACCENT_POLICY for SetWindowCompositionAttribute (attribute 19)."""

    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


_WCA_ACCENT_POLICY = 19
_ACCENT_DISABLED = 0


def _set_window_accent(hwnd: int, state: int, tint: int, flags: int) -> bool:
    """Ask the compositor for a material behind the window's own painting.

    Never raises: an old Windows build without the entry point, a bad handle or a
    refused policy all have to leave the window exactly as it looked before.
    """
    try:
        policy = _ACCENT_POLICY()
        policy.AccentState = state
        policy.AccentFlags = flags
        policy.GradientColor = tint
        data = _WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = _WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.byref(policy), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(policy)
        user32 = ctypes.windll.user32
        return bool(user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def _transparency_effects_enabled() -> bool:
    """Read Windows' own "transparency effects" switch (read only, never writes).

    With it switched off the accent call above still reports success and silently
    paints nothing, so this is the only way to know that the blur will not be
    there. The value is absent until the user touches the setting; Windows
    defaults it to on.
    """
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "EnableTransparency")
        return int(value) != 0
    except Exception:
        return True


class _MinimizeNativeFilter(QAbstractNativeEventFilter):
    """Application-level filter that catches taskbar minimize before Qt dispatches it."""

    # SetWindowPos flags used to ignore non-minimize position changes.
    _SWP_NOSIZE = 0x0001
    _SWP_HIDEWINDOW = 0x0080

    def __init__(self, window: "AfterFrameWindow") -> None:
        super().__init__()
        self._window = window
        self._hwnd = 0

    def set_hwnd(self, hwnd: int) -> None:
        self._hwnd = hwnd

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        if self._hwnd == 0:
            return False, 0
        try:
            msg_ptr = ctypes.cast(int(message), ctypes.POINTER(ctypes.wintypes.MSG))
            msg = msg_ptr.contents
            if msg.hwnd != self._hwnd:
                return False, 0
            if msg.message == 0x0112:  # WM_SYSCOMMAND
                if (msg.wParam & 0xFFF0) == 0xF020:  # SC_MINIMIZE
                    # Avoid re-entry if our own showMinimized() generates the same message.
                    if (
                        not self._window.isMinimized()
                        and self._window._minimize_animator is None
                    ):
                        self._window.animate_minimize()
                    return True, 0
            elif msg.message == 0x0046:  # WM_WINDOWPOSCHANGING
                # Some taskbar/system paths minimize via ShowWindow/SWP instead of
                # WM_SYSCOMMAND. Intercept the position change before it happens.
                wp_ptr = ctypes.cast(msg.lParam, ctypes.POINTER(_WINDOWPOS))
                wp = wp_ptr.contents
                if (
                    not (wp.flags & self._SWP_NOSIZE)
                    and not (wp.flags & self._SWP_HIDEWINDOW)
                    and wp.cx < MAIN_WINDOW_MIN_WIDTH
                    and wp.cy < MAIN_WINDOW_MIN_HEIGHT
                    and self._window.isVisible()
                    and not self._window.isMinimized()
                    and self._window._minimize_animator is None
                ):
                    self._window.animate_minimize()
                    return True, 0
            # This is a Win32 hook on a message we do not own;
            # anything unexpected must fall through unconsumed.
        except Exception:
            pass
        return False, 0


class _Spring1D:
    """One scalar of damped-spring physics, advanced once per frame.

    Same integrator as the elastic sliders on the music page, so the resize
    bounce and those controls share one feel. Defaults are the "sticky,
    QQ-candy" values used there.
    """

    __slots__ = ("value", "target", "velocity")

    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0

    def reset(self, value: float) -> None:
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0

    def push(self, target: float) -> None:
        self.target = float(target)

    def step(self, stiffness: float = 0.15, damping: float = 0.55) -> None:
        force = (self.target - self.value) * stiffness
        self.velocity += force - self.velocity * damping
        self.value += self.velocity

    def add_velocity(self, velocity: float) -> None:
        self.velocity += float(velocity)

    def done(self, pos_eps: float = 0.4, vel_eps: float = 0.4) -> bool:
        return abs(self.target - self.value) < pos_eps and abs(self.velocity) < vel_eps


class AfterFrameWindow(QWidget):
    """Borderless window: plays an intro animation, then becomes a main window."""

    def __init__(self) -> None:
        super().__init__()

        self._bar_x: float = float(BAR_LEFT_PADDING)
        self._bar_alpha: float = 255.0
        self._window_alpha: float = 1.0
        self._is_main_window = False
        self._intro_text_progress: float = 0.0

        self._trail: List[Tuple[float, int]] = []  # (bar_x, age_ms)
        self._elapsed = QElapsedTimer()
        self._elapsed.start()

        self._title_bar: CustomTitleBar = None
        self._sidebar: Sidebar = None
        self._main_container: QWidget = None
        # True once the compositor's blur material is live behind the chrome; the
        # chrome strips are only left unpainted while it is.
        self._chrome_glass = False
        # How far the chrome has been flattened: 0 shows the material, 1 paints
        # the strips opaque, which is the only chrome a snapshot can contain.
        # Animated around minimize / close / restore (`_begin_chrome_flatten`).
        self._chrome_flat = 0.0
        # Set while a minimize is waiting for that fade; also what runs when the
        # current fade reaches its end (None for a fade back to frosted).
        self._minimize_armed = False
        self._after_chrome_flatten = None

        # Spring-physics window dragging state.
        self._spring_timer = QTimer(self)
        self._spring_timer.timeout.connect(self._update_spring_physics)
        self._spring_timer.setInterval(16)
        self._spring_target = QPointF()
        self._spring_current = QPointF()
        self._spring_velocity = QPointF()
        self._spring_dragging = False
        self._spring_drag_offset = QPointF()
        self._normal_size = QSize(MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT)
        # Manual drag-resize state (frameless windows get no OS resize frame).
        self._resizing_edges = Qt.Edges()
        self._resize_start_global = None
        self._resize_start_geometry = None
        self._resize_target_geometry = None
        self._resize_drag_prev = None
        self._resize_drag_velocity = QPointF(0.0, 0.0)
        self._resize_drag_stamp = 0
        self._last_grip_edges = None
        # Springy settle after a resize ("Q弹" release).
        self._resize_springs = []
        self._resize_spring_settled = None
        self._resize_spring_pins = (True, True)
        self._resize_spring_timer = QTimer(self)
        self._resize_spring_timer.timeout.connect(self._update_resize_spring)
        self._resize_spring_timer.setInterval(16)
        self._closing = False
        self._close_animator = None
        self._minimize_animator = None
        self._minimize_pixmap = None
        self._restore_animator = None
        self._pre_minimize_geo = None
        self._toy_page = None
        self._native_filter = _MinimizeNativeFilter(self)

        self._setup_window()
        self._setup_animations()
        self._setup_trail_timer()

    # ------------------------------------------------------------------
    # Property definitions for animations
    # ------------------------------------------------------------------
    @Property(float)
    def bar_x(self) -> float:
        return self._bar_x

    @bar_x.setter
    def bar_x(self, value: float) -> None:
        self._bar_x = value
        self.update()

    @Property(float)
    def bar_alpha(self) -> float:
        return self._bar_alpha

    @bar_alpha.setter
    def bar_alpha(self, value: float) -> None:
        self._bar_alpha = max(0.0, min(255.0, value))
        self.update()

    @Property(float)
    def window_alpha(self) -> float:
        return self._window_alpha

    @window_alpha.setter
    def window_alpha(self, value: float) -> None:
        self._window_alpha = max(0.0, min(1.0, value))
        self.update()

    @Property(float)
    def chrome_flat(self) -> float:
        return self._chrome_flat

    @chrome_flat.setter
    def chrome_flat(self, value: float) -> None:
        self._chrome_flat = max(0.0, min(1.0, value))
        self.update()

    @Property(float)
    def intro_text_progress(self) -> float:
        return self._intro_text_progress

    @intro_text_progress.setter
    def intro_text_progress(self, value: float) -> None:
        self._intro_text_progress = max(0.0, min(1.0, value))
        self.update()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _setup_window(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        # Border grip: a frameless window gets no resize frame from the OS, and
        # every border pixel is covered by a child widget, so this filter has to
        # intercept those child mouse events before they are delivered.
        self.setMouseTracking(True)
        self.installEventFilter(self)

        cursor = QCursor.pos()
        self.setGeometry(cursor.x(), cursor.y(), INITIAL_SIZE, INITIAL_SIZE)

    def _setup_animations(self) -> None:
        # 1) Intro expansion from 1x1 to small window, centered on cursor.
        center = self.geometry().center()
        target_rect = QRect(
            center.x() - WINDOW_WIDTH // 2,
            center.y() - WINDOW_HEIGHT // 2,
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
        )

        self._expand_anim = QPropertyAnimation(self, b"geometry")
        self._expand_anim.setDuration(EXPAND_DURATION)
        self._expand_anim.setStartValue(self.geometry())
        self._expand_anim.setEndValue(target_rect)
        self._expand_anim.setEasingCurve(EXPAND_EASING)
        self._expand_anim.finished.connect(self._start_flash)

        # 2) Flash: bar alpha pulses a few times.
        self._flash_group = QSequentialAnimationGroup(self)
        flash_step = FLASH_DURATION // (FLASH_COUNT * 2)
        for i in range(FLASH_COUNT * 2):
            anim = QPropertyAnimation(self, b"bar_alpha")
            anim.setDuration(flash_step)
            if i % 2 == 0:
                anim.setStartValue(255.0)
                anim.setEndValue(60.0)
            else:
                anim.setStartValue(60.0)
                anim.setEndValue(255.0)
            anim.setEasingCurve(QEasingCurve.InOutSine)
            self._flash_group.addAnimation(anim)
        self._flash_group.finished.connect(self._start_move)

        # 3) Bar moves from left to off-screen right.
        self._move_anim = QPropertyAnimation(self, b"bar_x")
        self._move_anim.setDuration(MOVE_DURATION)
        self._move_anim.setStartValue(float(BAR_LEFT_PADDING))
        self._move_anim.setEndValue(float(WINDOW_WIDTH + BAR_WIDTH + 20))
        self._move_anim.setEasingCurve(MOVE_EASING)
        self._move_anim.finished.connect(self._finish_intro)

        # 4) Transition to main window: move to screen center and expand.
        self._main_expand_anim = QPropertyAnimation(self, b"geometry")
        self._main_expand_anim.setDuration(TRANSITION_TO_MAIN_DURATION)
        self._main_expand_anim.setEasingCurve(TRANSITION_TO_MAIN_EASING)
        self._main_expand_anim.finished.connect(self._on_main_window_ready)

        # 5) Intro text morphs into the title bar label during transition.
        self._text_morph_anim = QPropertyAnimation(self, b"intro_text_progress")
        self._text_morph_anim.setDuration(TRANSITION_TO_MAIN_DURATION)
        self._text_morph_anim.setStartValue(0.0)
        self._text_morph_anim.setEndValue(1.0)
        self._text_morph_anim.setEasingCurve(TRANSITION_TO_MAIN_EASING)

        # 6) Startup reveal: a coloured band sweeps the grown window left to
        #    right and the real UI appears in its wake.
        self._wipe_progress = 0.0
        self._wipe_enabled = _read_bool_setting(SETTINGS_KEY_WIPE, True)
        # How frosted the chrome is, as an index into FROSTED_LEVELS. Level 0
        # means "no material at all", which is also what a machine that cannot do
        # the material falls back to; the default level is how the window has
        # looked since the material was added, for anyone who never touched it.
        self._frosted_level = read_frosted_level()
        self._pending_music_dir = ""
        self._wipe_anim = QPropertyAnimation(self, b"wipeProgress")
        self._wipe_anim.setDuration(WIPE_DURATION)
        self._wipe_anim.setStartValue(0.0)
        self._wipe_anim.setEndValue(1.0)
        self._wipe_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._wipe_anim.finished.connect(self._on_wipe_finished)
        self._settings_page_index = -1

        # 7) Frosted chrome flattens before minimize/close and comes back after a
        #    restore: the material lives behind the window and cannot be captured,
        #    so the window is made to look like the snapshot instead of the other
        #    way round (see `_begin_chrome_flatten`).
        self._chrome_flat_anim = QPropertyAnimation(self, b"chrome_flat")
        self._chrome_flat_anim.setDuration(CHROME_FLAT_DURATION)
        self._chrome_flat_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._chrome_flat_anim.finished.connect(self._on_chrome_flatten_finished)

    def _setup_trail_timer(self) -> None:
        self._trail_timer = QTimer(self)
        self._trail_timer.setInterval(TRAIL_SAMPLE_INTERVAL_MS)
        self._trail_timer.timeout.connect(self._update_trail)

    # ------------------------------------------------------------------
    # Spring-physics window drag
    # ------------------------------------------------------------------
    def start_spring_drag(self, global_mouse_pos) -> None:
        """Begin a jelly-style drag of the entire window."""
        if self.isMaximized():
            self.showNormal()

        top_left = self.frameGeometry().topLeft()
        self._spring_drag_offset = QPointF(global_mouse_pos - top_left)
        self._spring_target = QPointF(top_left)
        self._spring_current = QPointF(top_left)
        self._spring_velocity = QPointF(0.0, 0.0)
        self._spring_dragging = True
        self._normal_size = self.size()
        self.setMinimumSize(0, 0)
        self._spring_timer.start()

    def update_spring_drag(self, global_mouse_pos) -> None:
        """Update the target position while the title bar is being dragged."""
        if not self._spring_dragging:
            return
        self._spring_target = QPointF(global_mouse_pos) - self._spring_drag_offset

    def stop_spring_drag(self) -> None:
        """Release the drag; the window keeps oscillating until it settles."""
        self._spring_dragging = False
        # Pull the target back fully on-screen so the window unsquishes.
        screen = QApplication.primaryScreen().geometry()
        max_x = screen.right() - self._normal_size.width() + 1
        max_y = screen.bottom() - self._normal_size.height() + 1
        self._spring_target.setX(
            max(screen.left(), min(max_x, int(self._spring_target.x())))
        )
        self._spring_target.setY(
            max(screen.top(), min(max_y, int(self._spring_target.y())))
        )

    def _screen_geometry(self) -> QRect:
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry()

    def _apply_screen_squeeze(self) -> None:
        """Clamp logical position to screen edges by compressing the window."""
        logical_rect = QRect(
            int(round(self._spring_current.x())),
            int(round(self._spring_current.y())),
            self._normal_size.width(),
            self._normal_size.height(),
        )
        screen = self._screen_geometry()

        squeeze_left = max(0, screen.left() - logical_rect.left())
        squeeze_right = max(0, logical_rect.right() - screen.right())
        squeeze_top = max(0, screen.top() - logical_rect.top())
        squeeze_bottom = max(0, logical_rect.bottom() - screen.bottom())

        actual_w = max(
            MAIN_WINDOW_MIN_WIDTH,
            logical_rect.width() - squeeze_left - squeeze_right,
        )
        actual_h = max(
            MAIN_WINDOW_MIN_HEIGHT,
            logical_rect.height() - squeeze_top - squeeze_bottom,
        )

        actual_x = logical_rect.left() + squeeze_left
        if actual_x + actual_w > screen.right():
            actual_x = screen.right() - actual_w + 1
        actual_y = logical_rect.top() + squeeze_top
        if actual_y + actual_h > screen.bottom():
            actual_y = screen.bottom() - actual_h + 1

        self.setGeometry(actual_x, actual_y, actual_w, actual_h)
        if self._is_main_window:
            self._pre_minimize_geo = self.geometry()

    def _update_spring_physics(self) -> None:
        # Tuned to be damped and "sticky": follows the mouse closely but
        # settles quickly without ringing back and forth.
        stiffness = 0.06
        damping = 0.45

        prev_current = QPointF(self._spring_current)
        force = self._spring_target - self._spring_current
        self._spring_velocity += force * stiffness - self._spring_velocity * damping
        self._spring_current += self._spring_velocity

        delta = self._spring_current - prev_current

        self._apply_screen_squeeze()

        if (
            not self._spring_dragging
            and abs(self._spring_velocity.x()) < 0.6
            and abs(self._spring_velocity.y()) < 0.6
            and abs(force.x()) < 0.6
            and abs(force.y()) < 0.6
        ):
            self._spring_timer.stop()
            self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
            self.setGeometry(
                int(round(self._spring_target.x())),
                int(round(self._spring_target.y())),
                self._normal_size.width(),
                self._normal_size.height(),
                        )

    def animate_minimize(self) -> None:
        """CRT-shutdown collapse before minimizing."""
        if self.isMinimized() or self._minimize_animator is not None:
            return
        if self._minimize_armed or self._closing:
            return
        if self.isMaximized():
            self.showMinimized()
            return

        # Make sure the real window is in a clean, fully-visible state before
        # we capture it. This prevents stale opacity/container state from a
        # previous taskbar fallback from leaking into this animation.
        if self._main_container is not None:
            self._main_container.show()
        self.setWindowOpacity(1.0)
        self.window_alpha = 1.0
        self.repaint()

        # Pre-roll: stop showing the frosted material before the snapshot below
        # is taken, so the collapse is drawn from the window as it really looks.
        self._minimize_armed = True
        if self._begin_chrome_flatten(self._minimize_after_flatten):
            return
        self._minimize_armed = False
        self._minimize_now()

    def _minimize_after_flatten(self) -> None:
        self._minimize_armed = False
        if self.isMinimized() or self._minimize_animator is not None or self._closing:
            return
        self._minimize_now()

    def _minimize_now(self) -> None:
        # Remember the real geometry; the window itself is not resized during
        # the animation. We make it fully transparent so only the CRT-shutdown
        # overlay is visible, but the window still owns its taskbar button.
        self._pre_minimize_geo = self.geometry()
        self._spring_timer.stop()
        self._spring_dragging = False

        # Cancel any stale restore animation left over from rapid minimize/restore.
        if self._restore_animator is not None:
            self._restore_animator.close()
            self._restore_animator = None

        # Capture the window content while it is still fully visible, then
        # show the CRT-shutdown overlay on top of it and hide the real window.
        # The stored snapshot is also reused for the restore animation so the
        # real UI never has to be shown during restore.
        pixmap = self._snapshot_for_animation()
        self._minimize_pixmap = pixmap
        self._minimize_animator = _MinimizeAnimator(self.geometry(), pixmap)
        self._minimize_animator.finished.connect(self._on_minimize_finished)

        self._minimize_animator.show()
        # Hide the real child UI so it cannot leak through the overlay band
        # or appear before the restore animation later.
        if self._main_container is not None:
            self._main_container.hide()
        self.window_alpha = 0.0
        self.update()
        self.showMinimized()

    def _on_minimize_finished(self) -> None:
        if self._minimize_animator is not None:
            self._minimize_animator.close()
            self._minimize_animator = None

        # If the user restored the window before the collapse finished, just
        # bring it back and skip re-minimizing.
        if not self.isMinimized():
            self.setWindowOpacity(1.0)
            self.window_alpha = 1.0
            if self._main_container is not None:
                self._main_container.show()
            self.repaint()
            # The collapse flattened the chrome on its way in; this window is
            # staying on screen, so put the frost back.
            self._restore_chrome_frost()
            return

        # Keep the window ready for the CRT restore animation.
        self.setWindowOpacity(1.0)
        self.window_alpha = 1.0
        self.repaint()

    def nativeEvent(self, event_type, message):
        """Intercept taskbar/system minimize so it plays the CRT animation."""
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                msg_ptr = ctypes.cast(
                    int(message), ctypes.POINTER(ctypes.wintypes.MSG)
                )
                msg = msg_ptr.contents
                if msg.message == 0x0112:  # WM_SYSCOMMAND
                    if (msg.wParam & 0xFFF0) == 0xF020:  # SC_MINIMIZE
                        self.animate_minimize()
                        return True, 0
                # As above, for the intro window's hook.
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _capture_minimize_snapshot(self) -> None:
        """Store a fresh snapshot of the window for the taskbar-minimize fallback."""
        if (
            self.isVisible()
            and not self.isMinimized()
            and self._main_container is not None
            and self._main_container.isVisible()
            and self._minimize_animator is None
            and self._restore_animator is None
            and self._close_animator is None
        ):
            try:
                self._minimize_pixmap = self._snapshot_for_animation()
                self._pre_minimize_geo = self.geometry()
                # Without a snapshot the minimize animation is skipped and
                # the window minimizes normally.
            except Exception:
                pass

    def _run_minimize_animation_from_snapshot(self) -> None:
        """Play the CRT shutdown overlay using the last stored snapshot.

        This path is used when Windows minimizes the window without going
        through our nativeEvent intercept (e.g. some taskbar clicks).
        """
        if self._minimize_animator is not None or self._minimize_armed:
            return
        pixmap = self._minimize_pixmap
        geo = self._pre_minimize_geo
        if pixmap is None or pixmap.isNull() or geo is None:
            return

        self._spring_timer.stop()
        self._spring_dragging = False

        if self._restore_animator is not None:
            self._restore_animator.close()
            self._restore_animator = None

        self._minimize_animator = _MinimizeAnimator(geo, pixmap)
        self._minimize_animator.finished.connect(self._on_minimize_finished)
        self._minimize_animator.show()
        if self._main_container is not None:
            self._main_container.hide()
        self.window_alpha = 0.0
        self.update()

    # ------------------------------------------------------------------
    # Frosted chrome (compositor material behind the title bar + sidebar)
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Idempotent and cheap; covers a window that was hidden and shown again.
        self._apply_chrome_glass()

    def _chrome_strips(self) -> List[Tuple[QWidget, QRect]]:
        """The chrome strips as (widget, window-coordinate rect), or [] before the UI exists.

        Only once the reveal has finished: while the container is masked the
        chrome is not painted at all, so unpainting the window underneath it
        would show raw blur with no wash over it.
        """
        if self._main_container is None or self._wipe_progress < 1.0:
            return []
        strips = []
        for widget in (self._title_bar, self._sidebar):
            if widget is None or not widget.isVisible():
                continue
            strips.append((widget, QRect(widget.mapTo(self, QPoint(0, 0)), widget.size())))
        return strips

    def _chrome_base(self, widget: QWidget) -> QColor:
        """The opaque colour under a strip's wash, from its theme.

        Not the window's BACKGROUND_COLOR: the bright pages keep a light chrome
        even when the wash is thin enough to show the blur, and a dark base there
        would drag them to mid grey the moment the material is unavailable (or
        faded out by the minimize/close pre-roll).
        """
        theme = getattr(widget, "_theme", None)
        base = theme.get("chrome_base") if isinstance(theme, dict) else None
        return QColor(base) if isinstance(base, QColor) else QColor(*BACKGROUND_COLOR)

    def _paint_chrome_backdrop(self, painter: QPainter) -> None:
        """Paint the chrome strips' BACKDROP: flat base colour plus the theme wash.

        This is what belongs *behind* the chrome, not instead of it: the strips
        are unpainted in our own rendering (that is where the compositor's
        material shows through on screen), so an offscreen grab has a hole there
        and the snapshot fills it with the look the window has when no material
        is available.
        """
        for widget, rect in self._chrome_strips():
            painter.fillRect(rect, self._chrome_base(widget))
            theme = getattr(widget, "_theme", None)
            wash = theme.get("chrome_bg") if isinstance(theme, dict) else None
            if isinstance(wash, QColor):
                painter.fillRect(rect, wash)

    def _snapshot_for_animation(self, content: QPixmap = None) -> QPixmap:
        """Snapshot for the minimize / restore / close overlays.

        The strips are painted OPAQUE and flat here: base colour plus the theme
        wash, with the chrome's own pixels (wash, title text, icons, window
        buttons) composited on top from the grab. The compositor's blur material
        is deliberately NOT in this image.

        Reading the material back off the screen was tried twice and abandoned:
        it needs a screen capture plus a Win32 hit test, and the result depends
        on the desktop, the DPI, what happens to be on top of the window and the
        capture timing. Both attempts measured fine in a probe on this machine
        and still came out as flat grey in the user's hands, which is the worst
        outcome available -- an animation that is sometimes frosted and sometimes
        see-through. A snapshot that is deliberately flat is at least honest and
        is exactly how these overlays looked before the frosted chrome existed.

        What makes that flat picture truthful instead of a lie is the pre-roll in
        `_begin_chrome_flatten`: minimize and close fade the chrome to flat BEFORE
        calling this, so at the moment of the grab the window really does look
        like what comes back, and a restored window melts the frost back in.
        """
        if content is None:
            try:
                content = self.grab()
            except Exception:
                content = QPixmap()
        if content.isNull():
            ratio = self.devicePixelRatioF()
            blank = QPixmap(int(self.width() * ratio), int(self.height() * ratio))
            blank.setDevicePixelRatio(ratio)
            blank.fill(QColor(*BACKGROUND_COLOR))
            painter = QPainter(blank)
            self._paint_chrome_backdrop(painter)
            painter.end()
            return blank
        # Flattened already (or no material at all): the strips were painted
        # opaque, so the grab has no hole and IS the picture -- filling the
        # backdrop in underneath would apply the theme wash a second time and
        # leave the animation slightly brighter than the window it replaces.
        if not self._chrome_glass or self._chrome_flat >= 0.999:
            return content
        canvas = QPixmap(content.size())
        canvas.setDevicePixelRatio(content.devicePixelRatio())
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        self._paint_chrome_backdrop(painter)
        painter.end()
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, content)
        painter.end()
        return canvas

    def _apply_chrome_glass(self) -> None:
        """(Re)apply the blur material. Never raises, never blocks the UI.

        The chrome strips are only unpainted while this reports True, so every
        failure -- the user's own switch, no handle, no entry point, or Windows'
        transparency effects switched off -- leaves the window looking exactly as
        it did before the material existed.
        """
        applied = False
        try:
            if self._frosted_level > 0 and _transparency_effects_enabled():
                hwnd = int(self.winId())
                applied = hwnd != 0 and _set_window_accent(
                    hwnd,
                    FROSTED_CHROME_STATE,
                    FROSTED_CHROME_TINT,
                    FROSTED_CHROME_FLAGS,
                )
        except Exception:
            applied = False
        if not applied:
            # Drop any stale material: the strips are painted opaque again, so a
            # leftover blur would only show through the theme's translucent wash.
            try:
                hwnd = int(self.winId())
                if hwnd:
                    _set_window_accent(hwnd, _ACCENT_DISABLED, 0, 0)
                # The accent call is cosmetic; a window without a handle yet just
                # keeps the previous chrome state.
            except Exception:
                pass
        if applied != self._chrome_glass:
            self._chrome_glass = applied
            self.update()

    def _chrome_frost_visible(self) -> bool:
        """Whether the blur material is really showing behind the chrome.

        The theme's wash sits on top of the material, and it differs per page:
        measured against a checkered backdrop the music page's thin wash (alpha
        26) leaves the blur at a luma sigma of 51.4, while the dashboard and
        settings pages (alpha 252) leave 0.70 -- invisible. Fading the chrome
        where it is invisible would only make every minimize wait ~200 ms for
        nothing, so the pre-roll is skipped unless a strip is thin enough to
        show the blur.
        """
        for widget, _rect in self._chrome_strips():
            theme = getattr(widget, "_theme", None)
            wash = theme.get("chrome_bg") if isinstance(theme, dict) else None
            if isinstance(wash, QColor) and wash.alpha() < CHROME_WASH_HIDES_FROST_ALPHA:
                return True
        return False

    def _begin_chrome_flatten(self, then) -> bool:
        """Fade the chrome from frosted to flat; True if *then* was deferred.

        The minimize / close overlays are drawn from a `grab()` of the window,
        and a grab has a HOLE where the strips are: the material lives behind the
        window, so no amount of reading our own pixels can capture it (reading the
        screen back was tried twice and abandoned -- see
        `_snapshot_for_animation`). Rather than chase the material, make the
        window stop showing it: fading `chrome_flat` to 1 paints the strips
        opaque, which is exactly the base colour plus wash that the snapshot would
        otherwise fill that hole with. By the time the pixmap is taken it is a
        truthful picture of the window, and the animation built from it has
        nothing to disagree with.

        Returns False when there is nothing to fade -- no material, no strips yet
        (the reveal has not finished), the page's wash hides the blur anyway, or
        already flat -- so the caller can run *then* immediately and pay no delay
        at all.
        """
        if not self._chrome_glass or not self._chrome_strips():
            return False
        if not self._chrome_frost_visible():
            return False
        if self._chrome_flat >= 0.999:
            return False
        self._run_chrome_fade(1.0, then)
        return True

    def _restore_chrome_frost(self) -> None:
        """Melt the frosted look back in once the real window is on screen again."""
        if self._after_chrome_flatten is not None:
            # A minimize or close is waiting for the chrome to flatten and owns
            # the animation right now. Taking it over here would drop that
            # callback -- for the close path that means the app never exits.
            return
        if not self._chrome_glass or not self._chrome_strips():
            # Nothing to fade over; keep the state honest for when it returns.
            self._set_chrome_flat(0.0)
            return
        if self._chrome_flat <= 0.001:
            return
        self._run_chrome_fade(0.0, None)

    def _run_chrome_fade(self, target: float, then) -> None:
        self._after_chrome_flatten = then
        self._chrome_flat_anim.stop()
        self._chrome_flat_anim.setStartValue(self._chrome_flat)
        self._chrome_flat_anim.setEndValue(target)
        self._chrome_flat_anim.start()

    def _set_chrome_flat(self, value: float) -> None:
        self._chrome_flat_anim.stop()
        self.chrome_flat = value

    def _on_chrome_flatten_finished(self) -> None:
        then = self._after_chrome_flatten
        self._after_chrome_flatten = None
        if then is not None:
            then()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange:
            # If the user is about to click the taskbar, capture the window now
            # so we have a fresh snapshot to animate from.
            if not self.isActiveWindow():
                self._capture_minimize_snapshot()
            return

        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized():
                # The window was minimized from outside our button. If we have a
                # snapshot, play the CRT shutdown animation over the desktop.
                if self._minimize_animator is None:
                    self._run_minimize_animation_from_snapshot()
                return
            # Restored from minimized: cancel any leftover CRT-shutdown
            # overlay, then bring back the original geometry, minimum size and
            # full opacity, and play the CRT startup reveal.
            if self._minimize_animator is not None:
                self._minimize_animator.close()
                self._minimize_animator = None

            self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
            if self._pre_minimize_geo is not None and not self.isMaximized():
                self.setGeometry(self._pre_minimize_geo)

            if self._restore_animator is None:
                # Keep the real UI hidden while restoring. Reuse the snapshot
                # taken at minimize time so we never have to render the live
                # window content before the CRT expand overlay is on screen.
                pixmap = self._minimize_pixmap
                if pixmap is None or pixmap.isNull():
                    pixmap = self._snapshot_for_animation()
                self.setWindowOpacity(0.0)
                self.window_alpha = 0.0
                if self._main_container is not None:
                    self._main_container.hide()
                screen = QApplication.screenAt(self.geometry().center())
                if screen is None:
                    screen = QApplication.primaryScreen()
                self._restore_animator = _RestoreAnimator(
                    screen.geometry(), self.geometry(), pixmap
                )
                self._restore_animator.finished.connect(
                    self._on_restore_finished
                )
                self._restore_animator.show()

    def _on_restore_finished(self) -> None:
        # Restore the real window content first, then remove the overlay,
        # to avoid a blank flash when the overlay disappears.
        self.setWindowOpacity(1.0)
        self.window_alpha = 1.0
        if self._main_container is not None:
            self._main_container.show()
        self._apply_chrome_glass()
        self.repaint()
        if self._restore_animator is not None:
            self._restore_animator.close()
            self._restore_animator = None
        # The window is showing the flat chrome the collapse ended on (the
        # restore overlay was drawn from that same picture, so there is nothing
        # to pop): melt the frosted material back in now that it is on screen.
        self._restore_chrome_frost()

    def animate_close(self) -> None:
        """Play the close animation and then exit the application."""
        if self._closing:
            return
        self._closing = True

        # Stop any ongoing drag/spring so the window geometry stays stable.
        self._spring_timer.stop()
        self._spring_dragging = False

        # Pre-roll, same reason as the minimize: the sweep is drawn from a
        # snapshot, and the material is not in a snapshot.
        if self._begin_chrome_flatten(self._close_now):
            return
        self._close_now()

    def _close_now(self) -> None:
        # Capture the window contents, then hide the real window and show the
        # fullscreen animator overlay.
        pixmap = self._snapshot_for_animation()
        screen = QApplication.screenAt(self.geometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        screen_geo = screen.geometry()
        window_geo = self.geometry()

        # Show the fullscreen animator first and defer hiding the real window
        # until the overlay has had a chance to paint, avoiding a blank flash.
        self._close_animator = _CloseAnimator(screen_geo, window_geo, pixmap)
        self._close_animator.finished.connect(self._on_close_finished)
        self._close_animator.show()
        QTimer.singleShot(0, self.hide)

    def _on_close_finished(self) -> None:
        QApplication.instance().quit()

    # ------------------------------------------------------------------
    # Animation sequence
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.show()
        self._native_filter.set_hwnd(int(self.winId()))
        self._apply_chrome_glass()
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._native_filter)
        self._expand_anim.start()

    def _start_flash(self) -> None:
        self._bar_x = float(BAR_LEFT_PADDING)
        self._bar_alpha = 255.0
        self._flash_group.start()

    def _start_move(self) -> None:
        self._bar_alpha = 255.0
        self._trail_timer.start()
        self._move_anim.start()

    def _update_trail(self) -> None:
        now = self._elapsed.elapsed()
        self._trail.append((self._bar_x, now))
        cutoff = now - TRAIL_MAX_AGE_MS
        self._trail = [(x, t) for x, t in self._trail if t > cutoff]
        if len(self._trail) > TRAIL_COUNT:
            self._trail = self._trail[-TRAIL_COUNT:]

    def _finish_intro(self) -> None:
        self._trail_timer.stop()
        self._start_main_window_transition()

    def _restore_music_dir(self) -> None:
        """Load the saved folder once the startup reveal is done."""
        path = getattr(self, "_pending_music_dir", "")
        self._pending_music_dir = ""
        if path and os.path.isdir(path) and self._toy_page is not None:
            # Loaded but paused: playback always starts from the music page.
            self._toy_page.set_music_dir(path, autoplay=False)

    def _start_main_window_transition(self) -> None:
        self._is_main_window = True

        screen = QApplication.primaryScreen().geometry()
        center_x = screen.center().x() - MAIN_WINDOW_WIDTH // 2
        center_y = screen.center().y() - MAIN_WINDOW_HEIGHT // 2
        target_rect = QRect(center_x, center_y, MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT)

        # Build the UI up front (rather than when the grow finishes) so the
        # reveal sweep runs *together* with the grow, with no pause between.
        self._setup_main_ui()
        self._pre_minimize_geo = self.geometry()

        # The intro name hands over to the revealed UI, so the morphing text is
        # dropped: un-swept areas must show nothing at all.
        self._intro_text_progress = 1.0

        if self._wipe_enabled:
            # Everything is grey at first: the container is masked away
            # completely, then revealed left to right.
            self._wipe_anim.stop()
            self.set_wipe_progress(0.0)
            self._wipe_anim.setStartValue(0.0)
            self._wipe_anim.setEndValue(1.0)
        else:
            self.set_wipe_progress(1.0)

        self._main_expand_anim.setStartValue(self.geometry())
        self._main_expand_anim.setEndValue(target_rect)
        self._main_expand_anim.start()
        if self._wipe_enabled:
            self._wipe_anim.start()
        else:
            self._restore_music_dir()

    def _on_main_window_ready(self) -> None:
        # The window has its final size now, so the minimum size can apply.
        self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        self._pre_minimize_geo = self.geometry()
        self._apply_wipe_mask()

    # ------------------------------------------------------------------
    # Startup reveal (grey window -> sweep -> real UI)
    # ------------------------------------------------------------------
    def get_wipe_progress(self) -> float:
        return self._wipe_progress

    def set_wipe_progress(self, value: float) -> None:
        self._wipe_progress = max(0.0, min(1.0, value))
        self._apply_wipe_mask()
        self.update()

    wipeProgress = Property(float, get_wipe_progress, set_wipe_progress)

    def _on_wipe_finished(self) -> None:
        self.set_wipe_progress(1.0)
        # Anything that costs more than a frame (tag reading, ffprobe) runs
        # after the reveal, never inside it.
        QTimer.singleShot(0, self._restore_music_dir)

    def _apply_wipe_mask(self) -> None:
        """Clip the main UI to the already-swept part of the window.

        Masking (instead of covering with a grey rectangle) means the un-swept
        area is painted by the window itself, so it is exactly the intro grey -
        no double-alpha seam where the two layers meet.
        """
        if self._main_container is None:
            return
        if self._wipe_progress >= 1.0:
            self._main_container.clearMask()
            return
        revealed = int(round(self.width() * self._wipe_progress))
        if revealed <= 0:
            self._main_container.setMask(QRegion())
        else:
            self._main_container.setMask(
                QRegion(0, 0, revealed, max(1, self.height()))
            )

    def _draw_wipe_edge(self, painter: QPainter, width: int, height: int) -> None:
        """The coloured band leading the reveal sweep."""
        x = width * self._wipe_progress
        band = max(70.0, width * 0.13)
        alpha = self._window_alpha

        lead = QColor(*BAR_COLOR)
        lead.setAlpha(int(200 * alpha))
        fade = QColor(*BAR_COLOR)
        fade.setAlpha(0)
        gradient = QLinearGradient(x, 0.0, x + band, 0.0)
        gradient.setColorAt(0.0, lead)
        gradient.setColorAt(0.30, QColor(BAR_COLOR[0], BAR_COLOR[1], BAR_COLOR[2], int(70 * alpha)))
        gradient.setColorAt(1.0, fade)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(QRectF(x, 0.0, band, float(height)))

        # Bright core line right on the boundary.
        core = QColor(232, 255, 190)
        core.setAlpha(int(235 * alpha))
        painter.setBrush(core)
        painter.drawRect(QRectF(x, 0.0, 2.0, float(height)))

    def _setup_main_ui(self) -> None:
        if self._main_container is not None:
            self._main_container.deleteLater()

        self._main_container = QWidget(self)
        self._main_container.setGeometry(self.rect())

        main_layout = QVBoxLayout(self._main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._title_bar = CustomTitleBar(self._main_container, self)
        main_layout.addWidget(self._title_bar)

        body = QWidget(self._main_container)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._sidebar = Sidebar(body)
        self._sidebar.add_icon("◈", "系统状态")
        self._sidebar.add_icon("✦", "音乐播放")
        self._sidebar.page_selected.connect(self._on_page_selected)
        body_layout.addWidget(self._sidebar)

        self._page_stack = PageStack(body)
        dashboard = SystemDashboard()
        self._page_stack.add_page(dashboard)
        toy_page = ToyPage()
        self._toy_page = toy_page
        self._page_stack.add_page(toy_page)
        self._page_stack.switch_started.connect(toy_page.set_switching)
        self._page_stack.switch_finished.connect(toy_page.set_switching)
        # The dashboard pauses its 60 fps background refresh during switches.
        self._page_stack.switch_started.connect(dashboard.set_switching)
        self._page_stack.switch_finished.connect(dashboard.set_switching)
        # The dashboard's checker floor borrows the music page's rhythm while
        # something plays: only its motion and brightness follow the music, its
        # colours stay its own (no cover palette). The music page keeps analysing
        # while hidden for exactly this reason.
        dashboard.set_rhythm_source(toy_page.music_rhythm)

        # Settings page lives outside the sidebar; it is opened from the
        # title bar button next to minimize.
        self._settings_page = SettingsPage()
        self._settings_page_index = self._page_stack.add_page(self._settings_page)
        self._settings_page.music_dir_changed.connect(self._on_music_dir_changed)
        self._settings_page.pcm_engine_changed.connect(
            self._on_pcm_engine_changed
        )
        self._settings_page.music_dir_cleared.connect(self._on_music_dir_cleared)
        self._settings_page.frosted_level_changed.connect(
            self._on_frost_level_changed
        )
        self._settings_page.hover_labels_changed.connect(
            self._on_hover_labels_changed
        )
        self._settings_page.lyrics_align_changed.connect(
            self._on_lyrics_align_changed
        )
        # The music page has its own folder picker. Persist what it picks and
        # mirror it into the settings page, otherwise the two pages disagree:
        # the folder is loaded on one page while the other still shows -- and
        # offers to clear -- the previous one.
        toy_page.music_dir_picked.connect(self._on_music_dir_picked)
        # The background visualisation is picked in that same submenu, so it is
        # remembered here rather than on the settings page -- like the last folder.
        toy_page.visualizer_changed.connect(self._on_visualizer_changed)
        # Player preferences. The saved folder is restored *after* the reveal
        # (it reads tags with ffprobe, which would stall the UI build).
        self._pending_music_dir = self._settings_page.current_music_dir()
        self._toy_page.set_pcm_engine_enabled(
            self._settings_page.pcm_engine_preference()
        )
        self._toy_page.set_row_tooltips(
            self._settings_page.hover_labels_preference()
        )
        # Where the lyrics sit: restored before the first paint, without looking
        # like a user change (see ToyPage.set_lyrics_align).
        self._toy_page.set_lyrics_align(read_lyrics_align())
        # Restore the saved visualisation before the first paint; an unknown or
        # missing key falls back to the default inside set_visualizer.
        self._toy_page.set_visualizer(
            _read_str_setting(SETTINGS_KEY_VISUALIZER), notify=False
        )

        body_layout.addWidget(self._page_stack, 1)

        main_layout.addWidget(body, 1)
        self._main_container.show()

        # Match the chrome to the page shown first (the bright dashboard).
        self._apply_page_theme(self._page_stack.current_index(), animate=False)

    def open_settings_page(self) -> None:
        """Open the settings page from the title bar button."""
        if self._page_stack is None or self._settings_page_index < 0:
            return
        self._title_bar.set_settings_active(True)
        self._sidebar.clear_selection()
        self._apply_page_theme(self._settings_page_index, animate=True)
        self._page_stack.switch_page(self._settings_page_index)

    def _on_music_dir_changed(self, path: str) -> None:
        if self._toy_page is not None:
            # Picking a folder from settings only prepares the playlist; the
            # user starts playback from the music page.
            self._toy_page.set_music_dir(path, autoplay=False)

    def _on_music_dir_cleared(self) -> None:
        if self._toy_page is not None:
            self._toy_page.clear_music_dir()

    def _on_music_dir_picked(self, path: str) -> None:
        """The music page picked a folder: save it and update the settings page.

        The music page has already loaded the folder itself, so nothing is sent
        back to it here. Persisting through the settings page keeps one writer
        for the setting, and refreshing its label is what makes the choice --
        and the "clear" button's state -- visible there.
        """
        self._settings_page.set_music_dir(path)

    def _on_pcm_engine_changed(self, enabled: bool) -> None:
        if self._toy_page is not None:
            self._toy_page.set_pcm_engine_enabled(enabled)

    def _on_hover_labels_changed(self, enabled: bool) -> None:
        """Settings switch: the popup menus' hover labels, on or off."""
        if self._toy_page is not None:
            self._toy_page.set_row_tooltips(enabled)

    def _on_lyrics_align_changed(self, index: int) -> None:
        """Settings slider: where the lyric lines sit."""
        if self._toy_page is not None:
            self._toy_page.set_lyrics_align(index)

    def _on_visualizer_changed(self, key: str) -> None:
        """Remember the background visualisation the user picked."""
        settings().setValue(SETTINGS_KEY_VISUALIZER, str(key))

    def _on_frost_level_changed(self, level: int) -> None:
        """Settings slider: takes effect immediately, no restart.

        Two things follow the level: whether the compositor material is used at
        all (level 0 turns it off) and how thick the wash over it is, so the
        current page is re-tinted as well. The same idempotent paths the window
        already uses on show/restore do the work.
        """
        self._frosted_level = int(level)
        self._apply_chrome_glass()
        self._apply_page_theme(self._page_stack.current_index(), animate=False)

    def _on_page_selected(self, index: int) -> None:
        self._title_bar.set_settings_active(False)
        self._apply_page_theme(index, animate=True)
        self._page_stack.switch_page(index)

    def _apply_page_theme(self, index: int, animate: bool = True) -> None:
        """Tint the sidebar and title bar to match the active page."""
        theme = theme_for_page(index, self._frosted_level)
        if self._sidebar is not None:
            self._sidebar.set_theme(theme, animate=animate)
        if self._title_bar is not None:
            self._title_bar.set_theme(theme, animate=animate)

    @staticmethod
    def _rgb_hex(color: Tuple[int, ...]) -> str:
        return "#" + "".join(f"{c:02x}" for c in color[:3])

    def system_resize_enabled(self) -> bool:
        """Whether a drag-resize may start right now.

        False during the intro (the window is still the 300x110 splash, which
        is smaller than the minimum size) and while any window animation owns
        the geometry, so a resize can never fight the animations. A settling
        resize bounce also blocks a new grab until it lands.
        """
        return (
            self._is_main_window
            and self.isVisible()
            and not self.isMinimized()
            and not self._closing
            and self._spring_dragging is False
            and self._minimize_animator is None
            and self._restore_animator is None
            and self._close_animator is None
            and not self._resize_spring_timer.isActive()
        )
    @staticmethod
    def _resize_grip_px(value: int) -> int:
        """Grip sizes are authored in logical px, so they need no DPI scaling.

        Getting this wrong is what made the first attempt nearly unusable: a
        physical-pixel value divided by a 200% device ratio left a 4-6 px
        logical strip to aim at.
        """
        return max(4, int(value))

    def _resize_grip_edges(self, pos) -> Qt.Edges:
        """Edges whose grip zone contains `pos` (window-local, logical px).

        Each axis is evaluated independently, so a point inside the corner box
        always yields both edges and gives diagonal resizing. The corner box is
        larger than the edge strip on purpose: aiming at a corner is imprecise,
        and an earlier per-axis early-return made corners resize on one axis
        only.
        """
        size = self.size()
        edge = self._resize_grip_px(RESIZE_BORDER)
        corner = self._resize_grip_px(RESIZE_CORNER)
        w = size.width()
        h = size.height()

        x = pos.x()
        y = pos.y()

        near_left = x < corner
        near_right = x >= w - corner
        near_top = y < corner
        near_bottom = y >= h - corner

        # A corner needs both axes, using the (larger) corner box.
        if (near_left or near_right) and (near_top or near_bottom):
            edges = Qt.Edges()
            edges |= Qt.LeftEdge if near_left else Qt.RightEdge
            edges |= Qt.TopEdge if near_top else Qt.BottomEdge
            return edges

        # Otherwise a single edge, using the narrower strip.
        edges = Qt.Edges()
        if x < edge:
            edges |= Qt.LeftEdge
        elif x >= w - edge:
            edges |= Qt.RightEdge
        if y < edge:
            edges |= Qt.TopEdge
        elif y >= h - edge:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_edges(edges: Qt.Edges) -> Qt.CursorShape:
        left = bool(edges & Qt.LeftEdge)
        right = bool(edges & Qt.RightEdge)
        top = bool(edges & Qt.TopEdge)
        bottom = bool(edges & Qt.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        if top or bottom:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def eventFilter(self, obj, event):  # noqa: N802
        """Own the window-edge grip, since every border pixel is a child widget.

        Installed on this window, so it sees child mouse events before the child
        does. Only presses inside the grip are consumed; everything else passes
        through untouched, keeping the jelly title-bar drag and all page
        interactions exactly as they were.

        The resize is driven here rather than by QWindow.startSystemResize(),
        which reports success on this window but leaves the geometry untouched.
        """
        etype = event.type()
        if etype == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton and self.system_resize_enabled():
                edges = self._resize_grip_edges(event.position().toPoint())
                if edges:
                    self._begin_manual_resize(edges, event.globalPosition())
                    return True
        elif etype == QEvent.MouseMove:
            if self._resizing_edges:
                self._update_manual_resize(event.globalPosition())
                return True
            # While the release spring plays, hold whatever cursor is showing:
            # resetting it the instant the button came up made the arrow snap
            # back while the window was still visibly springing open.
            if self._resize_spring_timer.isActive():
                return super().eventFilter(obj, event)
            if self.system_resize_enabled():
                self._update_grip_cursor(
                    self._resize_grip_edges(event.position().toPoint())
                )
            else:
                self._clear_grip_cursor()
        elif etype == QEvent.MouseButtonRelease:
            if self._resizing_edges:
                self._end_manual_resize()
                return True
        elif etype == QEvent.Leave:
            self._clear_grip_cursor()
        return super().eventFilter(obj, event)

    def _update_grip_cursor(self, edges: Qt.Edges) -> None:
        """Show a resize cursor inside the grip, restore the default outside it."""
        if not edges:
            self._clear_grip_cursor()
            return
        if edges != self._last_grip_edges:
            # Entering the grip, or moving between differently-shaped zones:
            # shadow whatever cursor the child widgets set for themselves.
            self.setCursor(QCursor(self._cursor_for_edges(edges)))
            self._last_grip_edges = edges

    def _clear_grip_cursor(self) -> None:
        if self._last_grip_edges is not None:
            self.unsetCursor()
            self._last_grip_edges = None

    def _begin_manual_resize(self, edges: Qt.Edges, global_pos) -> None:
        """Remember the frame the drag starts from."""
        # A settling bounce from a previous resize would fight this one.
        self._stop_resize_spring()
        # Our own minimum-size floor would fight the drag while it runs; the
        # clamp in _target_rect_for_drag enforces the real floor per axis.
        self.setMinimumSize(0, 0)
        self._resizing_edges = edges
        self._resize_start_global = global_pos.toPoint()
        self._resize_start_geometry = self.geometry()
        self._resize_target_geometry = self.geometry()
        self._resize_drag_prev = global_pos.toPoint()
        self._resize_drag_velocity = QPointF(0.0, 0.0)
        self._resize_drag_stamp = self._elapsed.elapsed()
        self.setCursor(QCursor(self._cursor_for_edges(edges)))

    @staticmethod
    def _squeeze_distance(raw: float) -> float:
        """How far the window actually gives when dragged `raw` px past minimum.

        A rubber band does not have a soft zone and then a wall: it gives a
        little at first, keeps giving less and less, and approaches its limit
        without ever quite stopping. That is a saturating curve,
        ``MAX * (raw / (raw + K)) ** power``, rather than a power curve with a
        cap -- a capped curve reads as two distinct regimes, which is exactly
        what makes it feel hard.
        """
        if raw <= 0.0:
            return 0.0
        if not MAIN_WINDOW_RESIZE_SQUEEZE:
            return 0.0
        ratio = raw / (raw + RESIZE_SQUEEZE_SOFTNESS)
        return RESIZE_SQUEEZE_MAX * (ratio ** RESIZE_SQUEEZE_POWER)

    def _target_rect_for_drag(self, global_pos) -> QRect:
        """Where the dragged edge wants the window to be, pre-spring.

        Past the minimum size the window is squeezed rather than pinned, so the
        drag keeps responding while the content stays whole.
        """
        start = self._resize_start_geometry
        delta = global_pos.toPoint() - self._resize_start_global
        edges = self._resizing_edges

        left = int(start.left())
        top = int(start.top())
        right = int(start.left() + start.width())
        bottom = int(start.top() + start.height())

        if edges & Qt.LeftEdge:
            left += delta.x()
        elif edges & Qt.RightEdge:
            right += delta.x()
        if edges & Qt.TopEdge:
            top += delta.y()
        elif edges & Qt.BottomEdge:
            bottom += delta.y()

        # Squeeze: turn the overshoot past the minimum into a diminishing give,
        # applied to the dragged edge so the anchored edge still never moves.
        width = right - left
        if width < MAIN_WINDOW_MIN_WIDTH:
            give = self._squeeze_distance(float(MAIN_WINDOW_MIN_WIDTH - width))
            if edges & Qt.LeftEdge:
                left = right - MAIN_WINDOW_MIN_WIDTH + give
            else:
                right = left + MAIN_WINDOW_MIN_WIDTH - give

        height = bottom - top
        if height < MAIN_WINDOW_MIN_HEIGHT:
            give = self._squeeze_distance(float(MAIN_WINDOW_MIN_HEIGHT - height))
            if edges & Qt.TopEdge:
                top = bottom - MAIN_WINDOW_MIN_HEIGHT + give
            else:
                bottom = top + MAIN_WINDOW_MIN_HEIGHT - give

        return QRect(left, top, right - left, bottom - top)

    def _update_manual_resize(self, global_pos) -> None:
        """Resize from the grabbed edge; the opposite edge stays pinned.

        The drag itself tracks the pointer 1:1 while the window is on screen --
        a spring here would feel like input lag. The bounce is added on release,
        in _end_manual_resize().
        """
        if self._resize_start_geometry is None:
            return

        now = global_pos.toPoint()
        step = now - self._resize_drag_prev
        self._resize_drag_prev = now

        # Pointer velocity in px/ms, decayed by real elapsed time rather than
        # by event count: a slow drag delivers long gaps between moves, and a
        # fixed per-event smoothing factor would either ignore those samples or
        # keep a stale first reading forever.
        stamp = self._elapsed.elapsed()
        last_stamp = self._resize_drag_stamp
        self._resize_drag_stamp = stamp
        dt = stamp - last_stamp
        if last_stamp and 0 < dt <= RESIZE_VELOCITY_STALE_MS:
            decay = math.exp(-dt / RESIZE_VELOCITY_TAU_MS)
            vx = step.x() / dt
            vy = step.y() / dt
            self._resize_drag_velocity = QPointF(
                self._resize_drag_velocity.x() * decay + vx * (1.0 - decay),
                self._resize_drag_velocity.y() * decay + vy * (1.0 - decay),
            )

        target = self._target_rect_for_drag(global_pos)
        self._resize_target_geometry = target
        self.setGeometry(target)

    def _end_manual_resize(self) -> None:
        target = self._resize_target_geometry or self.geometry()
        self._resize_start_geometry = None
        self._resize_target_geometry = None
        # The grip cursor is deliberately left in place: the window is about to
        # spring back, and dropping to an arrow mid-animation looks like a
        # glitch. It clears on the next mouse move once the bounce has landed.
        self._last_grip_edges = self._resizing_edges
        # The minimum-size floor stays lifted while the release spring plays:
        # putting it back here would snap the window out of its squeeze
        # instantly instead of letting it spring open. _stop_resize_spring()
        # restores it once the window has landed.
        # _start_resize_spring still needs to know which edges were grabbed in
        # order to inject the release velocity, so clear the state after it runs.
        self._start_resize_spring(target)
        self._resizing_edges = Qt.Edges()

    def _clamp_to_screen(self, rect: QRect) -> QRect:
        """Keep the window fully on its screen, shrinking then moving if needed.

        The drag itself is free to run the grabbed edge past the screen edge --
        that reads as "the window is now that big" rather than as the window
        sliding around. Only the released result is pulled back into view.
        """
        screen = self._screen_geometry()
        width = max(MAIN_WINDOW_MIN_WIDTH, min(rect.width(), screen.width()))
        height = max(MAIN_WINDOW_MIN_HEIGHT, min(rect.height(), screen.height()))
        left = min(max(rect.left(), screen.left()), screen.right() - width + 1)
        top = min(max(rect.top(), screen.top()), screen.bottom() - height + 1)
        return QRect(left, top, width, height)

    # ------------------------------------------------------------------
    # Springy release ("Q弹" settle after a resize)
    # ------------------------------------------------------------------
    def _apply_resize_spring_values(self, left, top, right, bottom) -> None:
        """Show one spring frame, keeping the anchored edges fixed.

        Each anchor takes its settled position, and the grabbed edge is allowed
        to keep its leap (even off-screen) by letting it extend past the frame --
        clamping it here would flatten the bounce into a crawl.
        """
        pins = self._resize_spring_pins
        settled = self._resize_spring_settled
        if settled is not None:
            if pins[0]:
                left = float(settled.left())
            if pins[1]:
                top = float(settled.top())

        # No minimum-size clamp here. A squeezed window's spring legitimately
        # starts below the minimum, and forcing the floor onto the very first
        # frame would stretch the geometry to the minimum instantly, swallowing
        # the animation. The spring targets are already at or above the floor,
        # and the kick only ever pushes outward.
        width = max(1, int(round(right - left)))
        height = max(1, int(round(bottom - top)))
        self.setGeometry(
            QRect(int(round(left)), int(round(top)), width, height)
        )

    def _start_resize_spring(self, target: QRect) -> None:
        """Overshoot slightly past the released size, then settle onto it.

        Each edge gets its own spring, so a corner drag ripples on both axes and
        the anchored edges travel with their side. The pointer speed recorded
        during the drag is injected as initial velocity, which is what makes a
        brisk drag bounce more than a slow one.
        """
        if target is None:
            return

        # A squeezed release is smaller than the minimum size; the spring's job
        # is then to push the window back open to the floor it was pressed past.
        # The window is left exactly where the drag put it -- no screen clamp
        # here, because moving it before the animation starts is itself the
        # jump we are trying to get rid of. Any off-screen correction is left
        # for the springs to travel through.
        released = target
        was_squeezed = (
            released.width() < MAIN_WINDOW_MIN_WIDTH
            or released.height() < MAIN_WINDOW_MIN_HEIGHT
        )
        target = QRect(
            released.left(),
            released.top(),
            max(released.width(), MAIN_WINDOW_MIN_WIDTH),
            max(released.height(), MAIN_WINDOW_MIN_HEIGHT),
        )
        settled_rect = target if was_squeezed else self._clamp_to_screen(target)
        width = settled_rect.width()
        height = settled_rect.height()
        left = settled_rect.left()
        top = settled_rect.top()
        settled = (left, top, left + width, top + height)
        self._resize_spring_settled = settled_rect

        if not MAIN_WINDOW_RESIZE_BOUNCE:
            self.setGeometry(settled_rect)
            self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
            return

        # Springs start at the size the pointer left the window at and are driven
        # by an initial velocity, never by jumping to an overshoot position --
        # jumping would show only the tail of the animation instead of the window
        # visibly springing. One outward kick on the grabbed edge covers both
        # cases: a squeezed window springs back open, an ordinary one springs
        # past the size it was released at.
        push_x = min(
            MAIN_WINDOW_RESIZE_OVERSHOOT,
            abs(self._resize_drag_velocity.x()) * RESIZE_RELEASE_VELOCITY_GAIN,
        )
        push_y = min(
            MAIN_WINDOW_RESIZE_OVERSHOOT,
            abs(self._resize_drag_velocity.y()) * RESIZE_RELEASE_VELOCITY_GAIN,
        )
        squeeze_kick_x = min(
            RESIZE_OPEN_VELOCITY_MAX,
            (settled[2] - settled[0]) * RESIZE_OPEN_VELOCITY_GAIN,
        )
        squeeze_kick_y = min(
            RESIZE_OPEN_VELOCITY_MAX,
            (settled[3] - settled[1]) * RESIZE_OPEN_VELOCITY_GAIN,
        )

        if self._resizing_edges & Qt.RightEdge:
            kick_x = abs(squeeze_kick_x) if was_squeezed else push_x
        elif self._resizing_edges & Qt.LeftEdge:
            kick_x = -abs(squeeze_kick_x) if was_squeezed else -push_x
        else:
            kick_x = 0.0
        if self._resizing_edges & Qt.BottomEdge:
            kick_y = abs(squeeze_kick_y) if was_squeezed else push_y
        elif self._resizing_edges & Qt.TopEdge:
            kick_y = -abs(squeeze_kick_y) if was_squeezed else -push_y
        else:
            kick_y = 0.0

        # Springs run from the released geometry onto the settled one; the
        # anchored edges stay put so the bounce reads as the grabbed edge
        # springing, not as the whole window sliding sideways.
        self._resize_spring_pins = (
            not (self._resizing_edges & Qt.LeftEdge),
            not (self._resizing_edges & Qt.TopEdge),
        )

        leap = (
            float(released.left()),
            float(released.top()),
            float(released.right() + 1),
            float(released.bottom() + 1),
        )
        springs = []
        for value, want in zip(leap, settled):
            spring = _Spring1D(value)
            spring.push(want)
            springs.append(spring)

        if self._resizing_edges & Qt.LeftEdge:
            springs[0].add_velocity(kick_x)
        elif self._resizing_edges & Qt.RightEdge:
            springs[2].add_velocity(kick_x)
        if self._resizing_edges & Qt.TopEdge:
            springs[1].add_velocity(kick_y)
        elif self._resizing_edges & Qt.BottomEdge:
            springs[3].add_velocity(kick_y)

        self._resize_springs = springs
        self._resize_spring_timer.start()

    def _update_resize_spring(self) -> None:
        springs = self._resize_springs
        if not springs:
            self._resize_spring_timer.stop()
            return

        for spring in springs:
            # Pass the constants, not the integrator's own defaults. `step()`
            # defaults to the drag spring's 0.55 damping, which overshoots once and
            # reads crisp; the resize spring is meant to wobble, and
            # RESIZE_SPRING_DAMPING (0.28) is what makes it. Calling step() bare left
            # those two constants with no effect at all, while this file's constants
            # and DEVELOPMENT.md both described them as the feel control.
            spring.step(RESIZE_SPRING_STIFFNESS, RESIZE_SPRING_DAMPING)

        if all(spring.done() for spring in springs):
            settled = self._resize_spring_settled
            self._stop_resize_spring()
            # Land exactly on the target geometry, not near it.
            if settled is not None:
                self.setGeometry(settled)
            return

        self._apply_resize_spring_values(*(s.value for s in springs))

    def _stop_resize_spring(self) -> None:
        self._resize_spring_timer.stop()
        self._resize_springs = []
        settled = self._resize_spring_settled
        self._resize_spring_settled = None
        if self._is_main_window and not self.isMinimized():
            # The floor was lifted for the drag/squeeze; put it back now that
            # the window has landed.
            self.setMinimumSize(MAIN_WINDOW_MIN_WIDTH, MAIN_WINDOW_MIN_HEIGHT)
        # A drag may be released with the window hanging off the screen; only
        # pull it back once the bounce has played out, so the spring is not
        # fighting the clamp while it animates.
        if settled is not None:
            clamped = self._clamp_to_screen(settled)
            if clamped != settled:
                self.setGeometry(clamped)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._main_container is not None:
            self._main_container.setGeometry(self.rect())
        if (
            self._is_main_window
            and not self._spring_dragging
            and not self._spring_timer.isActive()
        ):
            self._normal_size = self.size()
        if (
            self._is_main_window
            and self.isVisible()
            and not self.isMinimized()
            and self._main_container is not None
            and self._main_container.isVisible()
        ):
            self._pre_minimize_geo = self.geometry()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if (
            self._is_main_window
            and self.isVisible()
            and not self.isMinimized()
            and self._main_container is not None
            and self._main_container.isVisible()
        ):
            self._pre_minimize_geo = self.geometry()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        # Background (sharp corners). With the blur material live the chrome
        # strips are left unpainted so that material is what shows behind them;
        # the page area always gets the fill -- a page that skips a frame during
        # a switch would otherwise ghost the desktop through.
        bg = QColor(*BACKGROUND_COLOR, int(BACKGROUND_ALPHA * self._window_alpha))
        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        path = QPainterPath()
        if WINDOW_CORNER_RADIUS > 0:
            path.addRoundedRect(0, 0, width, height, WINDOW_CORNER_RADIUS, WINDOW_CORNER_RADIUS)
        else:
            path.addRect(0, 0, width, height)
        strips = self._chrome_strips()
        if self._chrome_glass and strips:
            region = QRegion(self.rect())
            for _widget, rect in strips:
                region -= QRegion(rect)
            painter.setClipRegion(region)
        painter.drawPath(path)
        painter.setClipping(False)

        # The strips carry the theme's OWN base, not the window's dark one. With
        # the material live they are painted only as far as the flatten fade has
        # come (`chrome_flat`; at 1 they are opaque pixels, which is exactly the
        # backdrop `_snapshot_for_animation` would fill that hole with), and with
        # no material at all they are painted outright -- that is what the chrome
        # looks like without the blur. See `_begin_chrome_flatten`.
        if strips:
            fill = self._chrome_flat if self._chrome_glass else 1.0
            if fill > 0.0:
                alpha = int(round(255 * self._window_alpha * fill))
                for widget, rect in strips:
                    base = self._chrome_base(widget)
                    base.setAlpha(alpha)
                    painter.fillRect(rect, base)

        if self._is_main_window:
            # Reveal sweep leading edge, then morph the intro text into the
            # title bar label.
            if 0.0 < self._wipe_progress < 1.0:
                self._draw_wipe_edge(painter, width, height)
            if self._intro_text_progress < 1.0:
                self._draw_morphing_text(painter)
            return

        if width <= 1 or height <= 1:
            return

        bar_y = 0
        bar_alpha_int = int(self._bar_alpha * self._window_alpha)

        # Trail / afterimage: same width/height as the bar, only opacity fades.
        if self._trail:
            now = self._elapsed.elapsed()
            for x, t in self._trail:
                age = now - t
                progress = 1.0 - (age / TRAIL_MAX_AGE_MS)
                progress = max(0.0, min(1.0, progress))
                if progress <= 0.01:
                    continue

                opacity = progress ** 1.8
                ghost_alpha = int(200 * opacity * self._window_alpha)
                ghost_color = QColor(*BAR_COLOR, ghost_alpha)
                painter.fillRect(
                    int(x - BAR_WIDTH / 2),
                    bar_y,
                    BAR_WIDTH,
                    BAR_HEIGHT,
                    ghost_color,
                )

        # Main bar
        if bar_alpha_int > 0:
            bar_color = QColor(*BAR_COLOR, bar_alpha_int)
            painter.fillRect(
                int(self._bar_x - BAR_WIDTH / 2),
                bar_y,
                BAR_WIDTH,
                BAR_HEIGHT,
                bar_color,
            )

        # Vertical version info fixed in the bottom-left corner.
        if self._window_alpha > 0.01:
            self._draw_vertical_version(painter, height)

        # App name revealed letter by letter (drawn on top of bar/trail).
        self._draw_text(painter, width, height)

    def _draw_morphing_text(self, painter: QPainter) -> None:
        """Draw the app name moving from the intro center to the title bar."""
        progress = self._intro_text_progress

        start_size = TEXT_FONT_SIZE
        end_size = 13
        current_size = int(start_size + (end_size - start_size) * progress)

        font = QFont(TEXT_FONT_FAMILY, current_size)
        font.setWeight(HEADING_WEIGHT)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(APP_NAME)

        # Start: centered in the intro window (fixed using the intro font metrics).
        intro_font = QFont(TEXT_FONT_FAMILY, TEXT_FONT_SIZE)
        intro_font.setWeight(HEADING_WEIGHT)
        intro_metrics = QFontMetrics(intro_font)
        intro_text_width = intro_metrics.horizontalAdvance(APP_NAME)
        start_x = (WINDOW_WIDTH - intro_text_width) / 2
        start_y = int(WINDOW_HEIGHT * TEXT_Y_OFFSET)

        # End: aligned with the title bar label.
        # Title bar layout: left margin 12, icon ~10px, spacing 6, baseline ~23.
        end_x = 28
        end_y = 23

        # Interpolate position.
        current_x = start_x + (end_x - start_x) * progress
        current_y = start_y + (end_y - start_y) * progress

        alpha = int(255 * (1.0 - progress) * self._window_alpha)
        if alpha <= 0:
            return

        color = QColor(*TEXT_COLOR, alpha)
        painter.setPen(QPen(color))
        painter.drawText(
            int(current_x),
            int(current_y - metrics.ascent()),
            int(text_width),
            int(metrics.height()),
            Qt.AlignLeft,
            APP_NAME,
        )

    def _draw_vertical_version(self, painter: QPainter, height: int) -> None:
        """Draw the version number vertically, fixed in the bottom-left corner."""
        version_font = QFont(TEXT_FONT_FAMILY, 7)
        version_font.setWeight(QFont.Medium)
        version_font.setLetterSpacing(QFont.PercentageSpacing, 110)

        metrics = QFontMetrics(version_font)
        text_width = metrics.horizontalAdvance(APP_VERSION_SHORT)
        text_height = metrics.height()

        text_pixmap = QPixmap(text_width, text_height)
        text_pixmap.fill(Qt.transparent)
        text_painter = QPainter(text_pixmap)
        text_painter.setFont(version_font)
        text_painter.setPen(
            QColor(*TEXT_SECONDARY_COLOR, int(130 * self._window_alpha))
        )
        text_painter.drawText(
            0, 0, text_width, text_height, Qt.AlignCenter, APP_VERSION_SHORT
        )
        text_painter.end()

        rotated = text_pixmap.transformed(
            QTransform().rotate(-90), Qt.SmoothTransformation
        )

        x = 5
        y = height - rotated.height() - 5
        painter.drawPixmap(x, y, rotated)

    def _draw_text(self, painter: QPainter, width: int, height: int) -> None:
        font = QFont(TEXT_FONT_FAMILY, TEXT_FONT_SIZE)
        font.setWeight(HEADING_WEIGHT)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        total_width = metrics.horizontalAdvance(APP_NAME)
        start_x = (width - total_width) / 2
        base_y = int(height * TEXT_Y_OFFSET)

        cumulative = 0.0
        for ch in APP_NAME:
            char_width = metrics.horizontalAdvance(ch)
            letter_center = start_x + cumulative + char_width / 2

            # Reveal the letter only after the bar has moved past it.
            reveal_threshold = letter_center + TEXT_REVEAL_BAND / 2
            distance = self._bar_x - reveal_threshold
            alpha_ratio = max(0.0, min(1.0, distance / TEXT_REVEAL_BAND))
            alpha = int(255 * alpha_ratio * self._window_alpha)

            if alpha > 0:
                color = QColor(*TEXT_COLOR, alpha)
                painter.setPen(QPen(color))
                painter.drawText(
                    int(start_x + cumulative),
                    int(base_y - metrics.ascent()),
                    int(char_width),
                    int(metrics.height()),
                    Qt.AlignCenter,
                    ch,
                )

            cumulative += char_width

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Click anywhere to close only during the intro animation.
        if not self._is_main_window:
            self.close()
