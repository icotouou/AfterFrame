"""Settings page: a cool glass page for the few knobs the app exposes.

Everything here is persisted with QSettings and applied immediately - the
window wires the signals to the player page and to the startup transition.
"""

import os

from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_FROSTED_LEVEL,
    DEFAULT_LYRICS_FADE,
    DEFAULT_LYRICS_SIZE,
    DEFAULT_LYRICS_ALIGN,
    FROSTED_LEVELS,
    HEADING_WEIGHT,
    LYRICS_ALIGNMENTS,
    LYRICS_SIZES,
    SETTINGS_KEY_FROSTED_CHROME,
    SETTINGS_KEY_FROSTED_LEVEL,
    SETTINGS_KEY_HOVER_LABELS,
    SETTINGS_KEY_LYRICS_ALIGN,
    SETTINGS_KEY_LYRICS_FADE,
    SETTINGS_KEY_LYRICS_SIZE,
    SETTINGS_KEY_MUSIC_DIR,
    SETTINGS_KEY_PCM_ENGINE,
    SETTINGS_KEY_WIPE,
    small_ui_font,
    ui_font,
)
from .dashboard import FX_BG_BOTTOM, FX_BG_TOP, FX_NAVY, paint_glass_panel
from .elastic_slider import ElasticSlider

# Right-hand control column: wide enough for the widest pair of buttons, but
# capped so a long music path wraps instead of stretching the row.
CONTROL_COLUMN_MAX_WIDTH = 240
from .scratch_engine import VinylAudioEngine
from .settings_store import settings as settings_store
from .settings_store import store_kind, store_path

# Small-text sizes, in POINTS, applied with `_small_font` rather than through a
# stylesheet.
#
# These used to be `font-size: 11px` in the stylesheets below. Pixels are the wrong
# unit here: a point size goes through Qt's DPI scaling and a pixel size does not,
# so on a 200%-scaled screen the pixel-sized text rendered at roughly two thirds of
# the height of the point-sized title next to it -- measured at device pixel ratio
# 2, the row title's glyphs came out 22 device pixels tall (ui_font(11)) against 14
# for the description (11px). Setting the font on the widget instead of in the
# stylesheet puts both through the same mechanism, and the stylesheet keeps only the
# colours.
#
# `ui_font` must not be called at import time (it builds a QFont), so the sizes live
# as numbers and the font is built where it is applied.
SETTINGS_DESC_PT = 9
SETTINGS_BUTTON_PT = 9


def _small_font(size: int = SETTINGS_DESC_PT, weight=None) -> QFont:
    """Interface font for the page's small text, in points (DPI-scaled).

    Uses `small_ui_font` rather than `ui_font`: at these sizes the preferred face
    draws Chinese strokes too thin to read cleanly, and the fix is the face, not the
    weight -- see the measurements on `small_ui_font`.
    """
    font = small_ui_font(size, weight)
    return font


def _read_bool(settings: QSettings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _read_int(settings: QSettings, key: str, default: int, low: int = 0,
              high: int = 1 << 30) -> int:
    """Read an integer preference, clamped; anything unreadable falls back."""
    try:
        return max(low, min(high, int(settings.value(key, default))))
    except (TypeError, ValueError):
        return default


def read_lyrics_align() -> int:
    """Saved lyric alignment index (0 left, 1 centre, 2 right), clamped.

    Read by the window as well: the music page needs it at startup, before the
    settings page exists.
    """
    return _read_int(
        settings_store(), SETTINGS_KEY_LYRICS_ALIGN, DEFAULT_LYRICS_ALIGN,
        0, len(LYRICS_ALIGNMENTS) - 1,
    )


def read_lyrics_size() -> int:
    """Saved lyric size index into LYRICS_SIZES (0 small, 1 medium, 2 large), clamped.

    Read by the window as well: the music page needs it at startup, before the settings page
    exists.
    """
    return _read_int(
        settings_store(), SETTINGS_KEY_LYRICS_SIZE, DEFAULT_LYRICS_SIZE,
        0, len(LYRICS_SIZES) - 1,
    )


def read_lyrics_fade() -> bool:
    """Whether the non-active lyric lines fade under the colour visualiser.

    Read by the window as well: the music page needs it at startup, before the settings page exists.
    """
    return _read_bool(settings_store(), SETTINGS_KEY_LYRICS_FADE, DEFAULT_LYRICS_FADE)


def read_frosted_level() -> int:
    """Saved frosted-chrome level, honouring the old on/off switch.

    Until the level control existed this preference was a boolean: off meant "no
    material at all" and on meant the standard look. An existing choice therefore
    still means what it used to, and only a machine that never touched it lands
    on the default level. Shared with the window, which needs the level before
    the settings page exists.
    """
    settings = settings_store()
    stored = settings.value(SETTINGS_KEY_FROSTED_LEVEL, None)
    if stored is not None:
        try:
            return max(0, min(len(FROSTED_LEVELS) - 1, int(stored)))
            # A stored level that is not a number means the setting was never
            # written; fall through to the default below.
        except (TypeError, ValueError):
            pass
    if not _read_bool(settings, SETTINGS_KEY_FROSTED_CHROME, True):
        return 0
    return DEFAULT_FROSTED_LEVEL


class _ElidedLabel(QLabel):
    """Single-line label that elides long text and keeps the full value as a
    tooltip, so a deep music path cannot be cut mid-glyph."""

    def __init__(self, text: str = "", parent: QWidget = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        super().setText(text)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        available = max(20, self.width() - 2)
        QLabel.setText(
            self, self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, available)
        )


class _LevelBar(QWidget):
    """Draggable picker for a small set of named levels.

    Used for the frosted-chrome strength and for the lyric alignment (the user
    asked for the second one to work and look exactly like the first). One
    continuous bar rather than a row of blocks -- the levels are marked by thin
    dividers -- with a green fill up to the current level, a handle riding its end
    and the level's name to the right. The handle is always on screen so the picked
    level is unmistakable, but it changes dress: a plain green ball while the
    control is at rest, and the music bar's white ball (with its green rim) once
    hovered or grabbed. The movement is the *same* spring model as the music page's
    seek bar (`ElasticSlider`, the module both pages import), so dragging between
    stops has the identical follow-through, hover thickening and wall bounce; a
    local 16 ms timer drives it and stops as soon as everything has settled, so a
    resting settings page costs nothing.
    """

    level_changed = Signal(int)

    HEIGHT = 26
    # The bar is inset from the widget's own left edge: the handle rides its end
    # and would otherwise be sliced off by the widget border at level 0 (seen on
    # screen before this pad existed).
    PAD = 12.0
    TRACK_WIDTH = 132.0  # the BAR's length, level 0 at its left end
    BAR_HEIGHT = 8.0  # resting thickness; grows by 80% while hovered/dragged
    NAME_GAP = 12.0
    NAME_ROOM = 64  # room for the level's name; fits a four-character label
    DIVIDER = 1.5
    # Fixed damping while dragging, instead of the music page's "faster drag, looser
    # spring" law. The frost handle must not fly past its stops, but both extremes
    # of the range were wrong: 0.85 (past critical) killed the springiness, and
    # 0.55 was still so tight that stops were overshot by only 0.3 px -- no visible
    # bounce at all. A sweep of the model settled on 0.50: a one-step fling past
    # the end goes from +14.1 px (music law) to +2.9 px, stops in between are
    # overshot by ~1.5 px, and it still settles in the same 336 ms as the music
    # page's bars.
    DRAG_DAMPING = 0.50
    # Drawing clamp on the spring's overshoot, so the handle can never be sliced
    # off by the widget even if a drag outruns the spring. The grabbed handle is
    # 8.2 px in radius and the bar starts 12 px in, so anything up to 0.029 of the
    # travel keeps it inside; 0.026 leaves a margin and still shows the bounce.
    MAX_OVERSHOOT = 0.026

    FRAME_MS = 16

    def __init__(self, labels, level: int, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._labels = [str(label) for label in labels]
        self._level = self._clamp(level)
        self._slider = ElasticSlider(self._fraction(self._level), self.DRAG_DAMPING)
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)
        # NAME_ROOM is the space the level's name gets to the right of the track.
        # 64 px fits a four-character label: the lyric row's original "靠左对齐"
        # measured 60 px and was being cut off by the 52 px this used to be (the
        # labels were shortened too, but the room should not be the thing that
        # decides how a label may read).
        self.setFixedSize(
            int(self.PAD * 2 + self.TRACK_WIDTH) + self.NAME_ROOM, self.HEIGHT
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # Value
    # ------------------------------------------------------------------
    def _clamp(self, level: int) -> int:
        return max(0, min(len(self._labels) - 1, int(level)))

    def _fraction(self, level: int) -> float:
        return level / max(1, len(self._labels) - 1)

    def level(self) -> int:
        return self._level

    def set_level(self, level: int, notify: bool = False) -> None:
        level = self._clamp(level)
        if level == self._level:
            return
        self._level = level
        self._slider.set_target(self._fraction(level))
        self._start()
        if notify:
            self.level_changed.emit(level)

    def _level_at(self, x: float) -> int:
        count = max(1, len(self._labels))
        if count == 1:
            return 0
        nearest = round((x - self.PAD) / self.TRACK_WIDTH * (count - 1))
        return self._clamp(int(nearest))

    # ------------------------------------------------------------------
    # Spring frames
    # ------------------------------------------------------------------
    def _start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        self._slider.update()
        self.update()
        if self._slider.settled():
            self._timer.stop()

    def is_animating(self) -> bool:
        """Whether the 16 ms timer is still running (used by the probes/tests)."""
        return self._timer.isActive()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def enterEvent(self, event) -> None:  # noqa: N802
        self._slider.hovered = True
        self._start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._slider.hovered = False
        self._start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._slider.dragging = True
            self.set_level(self._level_at(event.position().x()), notify=True)
            self._start()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._slider.dragging:
            self.set_level(self._level_at(event.position().x()), notify=True)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._slider.dragging = False
            self._start()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        slider = self._slider
        # Clamp the drawn overshoot: the spring may outrun the ends for a moment,
        # but the handle must not leave the widget (see MAX_OVERSHOOT).
        value = max(-self.MAX_OVERSHOOT, min(1.0 + self.MAX_OVERSHOOT, slider.visual))
        # Same growth rule as the music page's bar: hover/drag thickens it.
        height = self.BAR_HEIGHT * (1.0 + 0.8 * slider.expand)
        top = (self.height() - height) / 2.0
        radius = max(3.0, height / 2.0)
        left, width = self.PAD, self.TRACK_WIDTH
        fill_end = left + value * width

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        # The track stretches to contain an overshooting fill, exactly like the
        # music page's bar does.
        track_left = min(left, fill_end)
        track_right = max(left + width, fill_end)
        painter.setBrush(QColor(30, 42, 62, 40))
        painter.drawRoundedRect(
            QRectF(track_left, top, track_right - track_left, height), radius, radius
        )

        fill_left = min(left, fill_end)
        fill_right = max(left, fill_end)
        if fill_right - fill_left > 0.1:
            painter.setBrush(QColor(118, 185, 0))
            painter.drawRoundedRect(
                QRectF(fill_left, top, fill_right - fill_left, height), radius, radius
            )

        # Level dividers, drawn twice so they read on both halves: light over the
        # green fill, dark over the empty track.
        count = max(1, len(self._labels))
        for index in range(1, count - 1):
            divider_x = left + width * self._fraction(index) - self.DIVIDER / 2.0
            for clip_left, clip_right, tint in (
                (fill_left, fill_right, QColor(255, 255, 255, 130)),
                (track_left, fill_left, QColor(30, 42, 62, 45)),
                (fill_right, track_right, QColor(30, 42, 62, 45)),
            ):
                if clip_right - clip_left <= 0.1:
                    continue
                painter.save()
                painter.setClipRect(QRectF(clip_left, top, clip_right - clip_left, height))
                painter.setBrush(tint)
                painter.drawRect(QRectF(divider_x, top, self.DIVIDER, height))
                painter.restore()

        # Handle. It is always on screen so the picked level is unmistakable, but
        # it changes dress: at rest a plain green ball proud of the bar (no white
        # anywhere), and once hovered or grabbed the white ball fades in inside
        # it, which leaves the green rim the music page's bar has.
        grab = min(1.0, max(0.0, slider.expand))
        handle_r = height / 2.0 + 2.5 - 1.5 * grab
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(118, 185, 0))
        painter.drawEllipse(QPointF(fill_end, top + height / 2.0), handle_r, handle_r)
        if grab > 0.02:
            painter.setBrush(QColor(255, 255, 255, int(245 * grab)))
            painter.drawEllipse(
                QPointF(fill_end, top + height / 2.0), handle_r - 1.5, handle_r - 1.5
            )

        painter.setPen(QColor(30, 42, 62, 190))
        # The level's name is small text: on the face that keeps its strokes.
        painter.setFont(small_ui_font(11))
        painter.drawText(
            QRectF(left + width + self.NAME_GAP, 0.0,
                   self.width() - left - width - self.NAME_GAP, float(self.height())),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._labels[self._level],
        )


class _SettingRow(QFrame):
    """One setting: title, description and a control, on a glass card."""

    def __init__(
        self,
        title: str,
        description: str,
        control: QWidget,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 16, 20, 16)
        layout.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(4)

        self._title = QLabel(title)
        title_font = ui_font(11)
        title_font.setWeight(HEADING_WEIGHT)
        self._title.setFont(title_font)
        self._title.setStyleSheet("color: #1E2A3E; background: transparent;")
        text_column.addWidget(self._title)

        self._description = QLabel(description)
        self._description.setWordWrap(True)
        self._description.setFont(_small_font())
        self._description.setStyleSheet(
            "color: rgba(30, 42, 62, 0.58); background: transparent;"
        )
        text_column.addWidget(self._description)
        layout.addLayout(text_column, 1)
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_glass_panel(
            painter, QRectF(self.rect()).adjusted(4.5, 4.5, -4.5, -4.5), 14.0
        )


class _ScrollEdgeFade(QWidget):
    """Softens the two edges of the settings scroll area.

    A row that is half scrolled past the viewport edge is otherwise sliced off in
    a hard line.  The band fades the page's own background colour over the
    content there, and only as strongly as there is content actually hidden on
    that side -- scrolled all the way up (or down) the band disappears, so
    nothing looks smudged when there is nothing to hide.
    """

    BAND = 26

    def __init__(self, parent: QWidget, scroll: QScrollArea) -> None:
        super().__init__(parent)
        self._scroll = scroll
        # Wheel and clicks belong to the scroll area underneath.
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        bar = scroll.verticalScrollBar()
        bar.valueChanged.connect(self.update)
        bar.rangeChanged.connect(self.update)

    @staticmethod
    def _band(color: QColor, y0: int, y1: int, strength: float, from_top: bool):
        solid = QColor(color)
        solid.setAlphaF(max(0.0, min(1.0, strength)))
        clear = QColor(color)
        clear.setAlphaF(0.0)
        grad = QLinearGradient(0, y0, 0, y1)
        grad.setColorAt(0.0, solid if from_top else clear)
        grad.setColorAt(1.0, clear if from_top else solid)
        return grad

    def paintEvent(self, event) -> None:  # noqa: N802
        bar = self._scroll.verticalScrollBar()
        if bar.maximum() <= 0:
            return
        painter = QPainter(self)
        above = bar.value()
        below = bar.maximum() - bar.value()
        if above > 0:
            painter.fillRect(
                0, 0, self.width(), self.BAND,
                self._band(FX_BG_TOP, 0, self.BAND, above / float(self.BAND), True),
            )
        if below > 0:
            painter.fillRect(
                0, self.height() - self.BAND, self.width(), self.BAND,
                self._band(FX_BG_BOTTOM, self.height() - self.BAND, self.height(),
                           below / float(self.BAND), False),
            )


class SettingsPage(QWidget):
    """Light, cool-glass settings page."""

    # Emitted when the user picks a different music folder.
    music_dir_changed = Signal(str)
    # Emitted when the saved folder is cleared (files are never touched).
    music_dir_cleared = Signal()
    # Emitted when the PCM turntable engine preference changes.
    pcm_engine_changed = Signal(bool)
    # Emitted when the startup wipe transition preference changes.
    wipe_changed = Signal(bool)
    # Emitted when the frosted (acrylic) chrome's strength changes, as a level
    # index into FROSTED_LEVELS (0 = no material at all).
    frosted_level_changed = Signal(int)
    # Emitted when the popup panels' hover labels are switched on/off.
    hover_labels_changed = Signal(bool)
    # Emitted when the lyric size changes, as an index into LYRICS_SIZES
    lyrics_size_changed = Signal(int)
    lyrics_fade_changed = Signal(bool)
    # Emitted when the lyric alignment changes, as an index into LYRICS_ALIGNMENTS
    # (0 left, 1 centre, 2 right).
    lyrics_align_changed = Signal(int)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._settings = settings_store()
        self._pcm_available = VinylAudioEngine.supported()

        # The rows scroll. There are now more of them than fit at the window's
        # minimum height, and a scroll area keeps every row at its natural height
        # instead of squeezing the descriptions (measured: at 600x560 the six rows
        # were compressed to 57-58 px each and every description lost its bottom
        # line). Same treatment as the playlist panel -- scrollbars hidden, wheel
        # scrolling, transparent viewport -- so nothing new appears on screen, and
        # the HUD title stays on the page itself and does not scroll away.
        content = QWidget()
        content.setAttribute(Qt.WA_TranslucentBackground)
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(12)
        rows.addWidget(self._build_music_dir_row())
        rows.addWidget(self._build_pcm_row())
        rows.addWidget(self._build_wipe_row())
        rows.addWidget(self._build_frosted_chrome_row())
        rows.addWidget(self._build_lyrics_align_row())
        rows.addWidget(self._build_lyrics_size_row())
        rows.addWidget(self._build_lyrics_fade_row())
        rows.addWidget(self._build_hover_labels_row())
        rows.addWidget(self._build_about_row())
        rows.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._scroll.setWidget(content)

        # Soft top/bottom edges over the scrolling rows. It is a child of the
        # PAGE rather than of the scroll area, so it stays put while the rows
        # move; the scroll area tells it when it has been resized by the layout.
        self._edge_fade = _ScrollEdgeFade(self, self._scroll)
        self._edge_fade.setGeometry(self._scroll.geometry())
        self._edge_fade.raise_()
        self._scroll.installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 0, 32, 28)
        layout.setSpacing(0)
        # Same top offset the rows had before: 32 px margin + the 66 px the drawn
        # HUD title block occupies.
        layout.addSpacing(98)
        layout.addWidget(self._scroll, 1)

    # ------------------------------------------------------------------
    # Rows
    # ------------------------------------------------------------------
    def _build_music_dir_row(self) -> _SettingRow:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self._dir_label = _ElidedLabel()
        self._dir_label.setFont(_small_font())
        self._dir_label.setStyleSheet(
            "color: rgba(30, 42, 62, 0.75); background: transparent;"
        )
        column.addWidget(self._dir_label)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)

        self._clear_dir_btn = QPushButton("清除目录")
        self._clear_dir_btn.setCursor(Qt.PointingHandCursor)
        self._clear_dir_btn.setFocusPolicy(Qt.NoFocus)
        self._clear_dir_btn.setFont(_small_font(SETTINGS_BUTTON_PT))
        self._clear_dir_btn.setStyleSheet(self._button_style())
        self._clear_dir_btn.setToolTip("只清除设置里记录的目录，不会删除任何文件")
        self._clear_dir_btn.clicked.connect(self._clear_music_dir)
        buttons.addWidget(self._clear_dir_btn)

        browse = QPushButton("选择文件夹")
        browse.setCursor(Qt.PointingHandCursor)
        browse.setFocusPolicy(Qt.NoFocus)
        browse.setFont(_small_font(SETTINGS_BUTTON_PT))
        browse.setStyleSheet(self._button_style())
        browse.clicked.connect(self._browse_music_dir)
        buttons.addWidget(browse)
        column.addLayout(buttons)

        row = _SettingRow(
            "音乐文件夹",
            "设置播放器页面的歌曲来源",
            self._wrap(column),
        )
        self._refresh_music_dir_label(self._settings.value(SETTINGS_KEY_MUSIC_DIR, ""))
        return row

    def _build_pcm_row(self) -> _SettingRow:
        self._pcm_check = QCheckBox("启用")
        self._pcm_check.setCursor(Qt.PointingHandCursor)
        self._pcm_check.setFocusPolicy(Qt.NoFocus)
        self._pcm_check.setFont(_small_font(SETTINGS_BUTTON_PT))
        self._pcm_check.setStyleSheet(self._checkbox_style())
        self._pcm_check.setChecked(
            self._pcm_available
            and _read_bool(self._settings, SETTINGS_KEY_PCM_ENGINE, True)
        )
        self._pcm_check.setEnabled(self._pcm_available)
        self._pcm_check.toggled.connect(self._on_pcm_toggled)

        description = (
            "用 ffmpeg 解码原始 PCM，倒搓时可播放真正的反向音频、音调随手速变化"
            "关闭后改用 Qt 播放器（倒搓为模拟效果）"
        )
        if not self._pcm_available:
            description = "未检测到 ffmpeg，PCM 引擎不可用（将使用 Qt 播放器）"
        return _SettingRow("PCM 搓碟引擎", description, self._pcm_check)

    def _build_wipe_row(self) -> _SettingRow:
        self._wipe_check = QCheckBox("启用")
        self._wipe_check.setCursor(Qt.PointingHandCursor)
        self._wipe_check.setFocusPolicy(Qt.NoFocus)
        self._wipe_check.setFont(_small_font(SETTINGS_BUTTON_PT))
        self._wipe_check.setStyleSheet(self._checkbox_style())
        self._wipe_check.setChecked(_read_bool(self._settings, SETTINGS_KEY_WIPE, True))
        self._wipe_check.toggled.connect(self._on_wipe_toggled)
        return _SettingRow(
            "启动擦除过渡",
            "程序启动动画",
            self._wipe_check,
        )

    def _build_frosted_chrome_row(self) -> _SettingRow:
        self._frost_level_slider = _LevelBar(
            [label for label, _alphas in FROSTED_LEVELS], read_frosted_level()
        )
        self._frost_level_slider.level_changed.connect(self._on_frost_level_changed)
        return _SettingRow(
            "磨砂玻璃外壳",
            "在此设置程序亚克力外壳的模糊程度",
            self._frost_level_slider,
        )

    def _build_lyrics_align_row(self) -> _SettingRow:
        self._lyrics_align_slider = _LevelBar(
            list(LYRICS_ALIGNMENTS),
            _read_int(self._settings, SETTINGS_KEY_LYRICS_ALIGN, DEFAULT_LYRICS_ALIGN),
        )
        self._lyrics_align_slider.level_changed.connect(self._on_lyrics_align_changed)
        return _SettingRow(
            "歌词位置",
            "在此设置音乐播放页面歌词的对齐方式",
            self._lyrics_align_slider,
        )

    def _build_lyrics_size_row(self) -> _SettingRow:
        self._lyrics_size_slider = _LevelBar(
            [label for label, _spec in LYRICS_SIZES],
            _read_int(self._settings, SETTINGS_KEY_LYRICS_SIZE, DEFAULT_LYRICS_SIZE),
        )
        self._lyrics_size_slider.level_changed.connect(self._on_lyrics_size_changed)
        return _SettingRow(
            "歌词大小",
            "在此设置音乐播放页面歌词的字号，以及一屏显示几句",
            self._lyrics_size_slider,
        )

    def _build_lyrics_fade_row(self) -> _SettingRow:
        self._lyrics_fade_check = QCheckBox("启用")
        self._lyrics_fade_check.setCursor(Qt.PointingHandCursor)
        self._lyrics_fade_check.setFocusPolicy(Qt.NoFocus)
        self._lyrics_fade_check.setFont(_small_font(SETTINGS_BUTTON_PT))
        self._lyrics_fade_check.setStyleSheet(self._checkbox_style())
        self._lyrics_fade_check.setChecked(
            _read_bool(self._settings, SETTINGS_KEY_LYRICS_FADE, DEFAULT_LYRICS_FADE)
        )
        self._lyrics_fade_check.toggled.connect(self._on_lyrics_fade_toggled)
        return _SettingRow(
            "歌词淡出",
            "可视化效果为音乐色彩时，非当前歌词淡出，只留形状；鼠标指向某句可临时恢复清晰",
            self._lyrics_fade_check,
        )

    def _build_hover_labels_row(self) -> _SettingRow:
        self._hover_labels_check = QCheckBox("启用")
        self._hover_labels_check.setCursor(Qt.PointingHandCursor)
        self._hover_labels_check.setFocusPolicy(Qt.NoFocus)
        self._hover_labels_check.setFont(_small_font(SETTINGS_BUTTON_PT))
        self._hover_labels_check.setStyleSheet(self._checkbox_style())
        self._hover_labels_check.setChecked(
            _read_bool(self._settings, SETTINGS_KEY_HOVER_LABELS, True)
        )
        self._hover_labels_check.toggled.connect(self._on_hover_labels_toggled)
        return _SettingRow(
            "子菜单悬停标签",
            "鼠标停在播放列表与可视化效果的选项上时，弹出显示完整文字的小标签",
            self._hover_labels_check,
        )

    def _build_about_row(self) -> _SettingRow:
        version = QLabel(f"{APP_VERSION.upper()}")
        version_font = ui_font(12)
        version_font.setWeight(QFont.Bold)
        version.setFont(version_font)
        version.setStyleSheet("color: #76B900; background: transparent;")
        # Say where the preferences actually went, and whether they can be written.
        #
        # Not decoration: the registry store can fail to persist WITHOUT raising and
        # without any error anywhere (see settings_store), and the only symptom is a
        # setting that forgets itself after a restart. Naming the store and its state
        # turns that from a mystery into something the user can see, and it is what
        # store_kind() was written for -- it had no caller before.
        kind = store_kind()
        description = "系统监控、音乐播放与黑胶搓碟 · 设置存储：%s" % (
            "注册表" if kind == "registry" else ("INI 文件" if kind == "ini" else "只读"),
        )
        if kind == "read-only":
            description += "（不可写，改动不会保留）"
        row = _SettingRow(APP_NAME, description, version)
        row.setToolTip("%s\n%s" % (kind, store_path()))
        return row

    @staticmethod
    def _wrap(layout) -> QWidget:
        """Wrap a control column, sized to its content but bounded so a long
        path cannot push the row's description out of the way."""
        holder = QWidget()
        holder.setAttribute(Qt.WA_StyledBackground, False)
        holder.setLayout(layout)
        holder.setMaximumWidth(CONTROL_COLUMN_MAX_WIDTH)
        return holder

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _button_style() -> str:
        # No font-size here on purpose: the size comes from `_small_font` in points
        # so it scales with the screen (see the note on SETTINGS_DESC_PT).
        return """
            QPushButton {
                background: rgba(255, 255, 255, 0.72);
                color: #1E2A3E;
                border: 1px solid rgba(30, 42, 62, 0.22);
                border-radius: 13px;
                padding: 4px 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.95);
                border: 1px solid rgba(64, 112, 188, 0.55);
            }
            QPushButton:pressed {
                background: rgba(118, 185, 0, 0.22);
            }
        """

    @staticmethod
    def _checkbox_style() -> str:
        # Colour and the switch geometry only; the label size comes from
        # `_small_font` in points (see the note on SETTINGS_DESC_PT).
        return """
            QCheckBox {
                color: rgba(30, 42, 62, 0.85);
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 34px;
                height: 18px;
                border-radius: 9px;
                background: rgba(30, 42, 62, 0.18);
                border: 1px solid rgba(30, 42, 62, 0.20);
            }
            QCheckBox::indicator:hover {
                background: rgba(30, 42, 62, 0.26);
            }
            QCheckBox::indicator:checked {
                background: #76B900;
                border: 1px solid rgba(70, 110, 0, 0.55);
            }
            QCheckBox:disabled {
                color: rgba(30, 42, 62, 0.35);
            }
            QCheckBox::indicator:disabled {
                background: rgba(30, 42, 62, 0.10);
            }
        """

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def current_music_dir(self) -> str:
        return str(self._settings.value(SETTINGS_KEY_MUSIC_DIR, "") or "")

    def pcm_engine_preference(self) -> bool:
        """Saved preference; False when ffmpeg is unavailable."""
        if not self._pcm_available:
            return False
        return _read_bool(self._settings, SETTINGS_KEY_PCM_ENGINE, True)

    def hover_labels_preference(self) -> bool:
        """Whether the popup panels should show their row hover labels."""
        return _read_bool(self._settings, SETTINGS_KEY_HOVER_LABELS, True)

    def _refresh_music_dir_label(self, path: str) -> None:
        if path and os.path.isdir(path):
            self._dir_label.setText(path)
        else:
            self._dir_label.setText("尚未设置")
        if hasattr(self, "_clear_dir_btn"):
            self._clear_dir_btn.setEnabled(bool(path))

    def sync_music_dir(self) -> None:
        """Re-read the saved folder and show it.

        The music page can change the folder too, so the label must never be
        driven by whatever value a caller happens to hold -- always re-read the
        single source of truth, otherwise the two pages disagree (the folder is
        set on one page but the other still shows the old one, and "clear" then
        appears to do nothing).
        """
        self._refresh_music_dir_label(self.current_music_dir())

    def set_music_dir(self, path: str) -> None:
        """Store a folder chosen elsewhere and show it.

        Does NOT emit `music_dir_changed`: that signal means "the user picked
        something on this page", and re-emitting it here would send the value
        straight back to the page it came from.
        """
        if path:
            self._settings.setValue(SETTINGS_KEY_MUSIC_DIR, path)
        else:
            self._settings.remove(SETTINGS_KEY_MUSIC_DIR)
        self._settings.sync()
        self.sync_music_dir()

    def _browse_music_dir(self) -> None:
        start = self.current_music_dir()
        folder = QFileDialog.getExistingDirectory(self, "选择音乐目录", start)
        if not folder:
            return
        self._settings.setValue(SETTINGS_KEY_MUSIC_DIR, folder)
        self._refresh_music_dir_label(folder)
        self.music_dir_changed.emit(folder)

    def _clear_music_dir(self) -> None:
        """Forget the saved folder. No files are removed."""
        self._settings.remove(SETTINGS_KEY_MUSIC_DIR)
        self._settings.sync()
        self._refresh_music_dir_label("")
        self.music_dir_cleared.emit()

    def _on_pcm_toggled(self, checked: bool) -> None:
        self._settings.setValue(SETTINGS_KEY_PCM_ENGINE, bool(checked))
        self.pcm_engine_changed.emit(bool(checked))

    def _on_wipe_toggled(self, checked: bool) -> None:
        self._settings.setValue(SETTINGS_KEY_WIPE, bool(checked))
        self.wipe_changed.emit(bool(checked))

    def _on_frost_level_changed(self, level: int) -> None:
        self._settings.setValue(SETTINGS_KEY_FROSTED_LEVEL, int(level))
        # The level supersedes the old on/off key; drop it so the two cannot
        # disagree if this build is ever rolled back to a boolean one.
        self._settings.remove(SETTINGS_KEY_FROSTED_CHROME)
        self.frosted_level_changed.emit(int(level))

    def _on_hover_labels_toggled(self, checked: bool) -> None:
        self._settings.setValue(SETTINGS_KEY_HOVER_LABELS, bool(checked))
        self.hover_labels_changed.emit(bool(checked))

    def _on_lyrics_fade_toggled(self, checked: bool) -> None:
        self._settings.setValue(SETTINGS_KEY_LYRICS_FADE, bool(checked))
        self.lyrics_fade_changed.emit(bool(checked))

    def _on_lyrics_size_changed(self, level: int) -> None:
        self._settings.setValue(SETTINGS_KEY_LYRICS_SIZE, int(level))
        self.lyrics_size_changed.emit(int(level))

    def _on_lyrics_align_changed(self, level: int) -> None:
        self._settings.setValue(SETTINGS_KEY_LYRICS_ALIGN, int(level))
        self.lyrics_align_changed.emit(int(level))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Keep the edge fade exactly where the layout puts the scroll area.

        The overlay has to be stacked above the scroll area to be visible at all,
        and showing the page re-stacks its children -- so the raise is asserted
        here and in `showEvent`, not just once in `__init__` (a single raise there
        left the fade underneath the scroll area, painting into nothing).
        """
        if obj is self._scroll and event.type() in (QEvent.Resize, QEvent.Move):
            self._edge_fade.setGeometry(self._scroll.geometry())
            self._edge_fade.raise_()
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._edge_fade.setGeometry(self._scroll.geometry())
        self._edge_fade.raise_()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        # Same Atmospheric gradient as the dashboard, so the chrome theme and
        # the page agree.
        bg = QLinearGradient(0, 0, w * 0.25, h)
        bg.setColorAt(0.0, FX_BG_TOP)
        bg.setColorAt(1.0, FX_BG_BOTTOM)
        painter.setBrush(bg)
        painter.drawRect(0, 0, w, h)

        # Corner brackets and the page title, echoing the dashboard HUD.
        m = 14
        size = 18
        bracket = QColor(FX_NAVY)
        bracket.setAlpha(70)
        painter.setPen(QPen(bracket, 1))
        painter.setBrush(Qt.NoBrush)
        for cx, cy, dx, dy in (
            (m, m, 1, 1),
            (w - m, m, -1, 1),
            (m, h - m, 1, -1),
            (w - m, h - m, -1, -1),
        ):
            painter.drawLine(cx, cy + dy * size, cx, cy)
            painter.drawLine(cx, cy, cx + dx * size, cy)

        title_font = ui_font(15)
        title_font.setWeight(QFont.Bold)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        painter.setFont(title_font)
        title = QColor(FX_NAVY)
        title.setAlpha(205)
        painter.setPen(title)
        painter.drawText(m + 10, m + 32, "SETTINGS")

        # "AFTERFRAME // PREFERENCES" -- 7pt Chinese/Latin caption, so the face that
        # holds its strokes at small sizes (see small_ui_font).
        caption_font = small_ui_font(7)
        caption_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        painter.setFont(caption_font)
        caption = QColor(FX_NAVY)
        caption.setAlpha(120)
        painter.setPen(caption)
        painter.drawText(m + 27, m + 43, "AFTERFRAME // PREFERENCES")

        accent = QColor(118, 185, 0)
        accent.setAlpha(200)
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRect(QRectF(m + 11, m + 40, 12, 2))

        underline = QColor(FX_NAVY)
        underline.setAlpha(46)
        painter.setPen(QPen(underline, 1))
        painter.drawLine(m + 10, m + 51, m + 10 + 128, m + 51)
