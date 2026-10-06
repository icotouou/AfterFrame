import json
import math
import os
import random
import re
import subprocess
from array import array

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPoint,
    QPointF,
    Property,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer

    MULTIMEDIA_AVAILABLE = True
except Exception:
    MULTIMEDIA_AVAILABLE = False
    QAudioOutput = QMediaMetaData = QMediaPlayer = None

try:
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4

    MUTAGEN_AVAILABLE = True
except Exception:
    MUTAGEN_AVAILABLE = False
    FLAC = MP3 = MP4 = None

from .color_extractor import ColorExtractor
from .constants import (
    BTN_PRESS_DAMPING,
    BTN_PRESS_KICK,
    BTN_PRESS_STIFFNESS,
    COLOR_BACKDROP_DARKEN,
    COLOR_BG_BLUR_DIVISOR,
    COLOR_BUBBLE_CLEARANCE,
    COLOR_BUBBLE_MIST_ALPHA,
    COLOR_BUBBLE_SWAY_RAD_PER_MS,
    COLOR_BUBBLE_SWAY_SPEEDUP,
    COLOR_BUBBLE_SWAY_X,
    COLOR_BUBBLE_SWAY_Y,
    COLOR_FROST_ALPHA,
    COLOR_FROST_DARKEN,
    COLOR_FRAME_STEP_MS,
    COLOR_MIST_BLOB_ALPHA,
    COLOR_MIST_BLOB_SIZE,
    COLOR_MIST_BLOBS,
    COLOR_MIST_BREATHE,
    COLOR_MIST_DIVISOR,
    COLOR_MIST_DRIFT_RAD_PER_S,
    COLOR_MIST_DRIFT_X,
    COLOR_MIST_DRIFT_Y,
    COLOR_NOISE_ALPHA,
    COLOR_NOISE_DRIFT_PX,
    COLOR_NOISE_STEP_MS,
    COLOR_NOISE_TILE,
    COLOR_RESIZE_SETTLE_MS,
    COLOR_SHAPE_MIST_ALPHA,
    COLOR_SHAPE_SPIN_DEG_PER_S,
    DEFAULT_LYRICS_ALIGN,
    DEFAULT_LYRICS_SIZE,
    HEADING_WEIGHT,
    INFO_SCROLL_HEAD_PAUSE_MS,
    INFO_SCROLL_SPEED_PX_S,
    INFO_SCROLL_TAIL_PAUSE_MS,
    LYRICS_ALIGNMENTS,
    LYRICS_SIZES,
    DEFAULT_LYRICS_FADE,
    MUSIC_SOURCE_NCM,
    no_window_kwargs,
    PAGE_TINT_ALPHA,
    PAGE_TINT_COLOR,
    SUPPORTED_AUDIO_EXTS,
    VINYL_BACKWARD_DRIFT_MS,
    VINYL_DRAG_LIFT_SCALE,
    VINYL_FORWARD_DRIFT_BASE_MS,
    VINYL_FORWARD_LAG_MS,
    VINYL_HOVER_LIGHT_ALPHA,
    VINYL_HOVER_LIGHT_RADIUS_RATIO,
    VINYL_INERTIA_TAU_MS,
    VINYL_LABEL_RADIUS_RATIO,
    VINYL_LABEL_RING_TEXT_SIZE_RATIO,
    VINYL_LABEL_TINT_BLEND,
    VINYL_LIFT_EASE_MS,
    VINYL_MAX_SCRATCH_DELTA_DEG,
    VINYL_MS_PER_DEG,
    VINYL_PEEK_FRACTION,
    VINYL_PULL_DRAG_PX,
    VINYL_RATE_RETURN_TAU_MS,
    VINYL_RATE_MIN,
    VINYL_RATE_MAX,
    VINYL_RELEASE_RATE_MIN,
    VINYL_RELEASE_RATE_MAX,
    VINYL_RELEASE_SPEED_CLAMP,
    VINYL_RELEASE_TAU_MS,
    VINYL_SCRATCH_SENSITIVITY,
    VINYL_SHEEN_ALPHA,
    VINYL_SPIN_DEG_PER_MS,
    VINYL_STOW_DRAG_PX,
    VINYL_VEL_EMA,
    VOLUME_ICON_MAX_OFFSET,
    VOLUME_ICON_PUSH_PX,
    VOLUME_ICON_WALL_KICK,
    ui_font,
)
from .elastic_slider import ElasticSlider
from .ncm import cover_pixmap, decode as decode_ncm
from .scratch_engine import VinylAudioEngine


def _blend_color(base: QColor, tint: QColor, ratio: float) -> QColor:
    """Blend *tint* into *base* by *ratio* (0..1)."""
    r = max(0.0, min(1.0, ratio))
    return QColor(
        int(base.red() * (1 - r) + tint.red() * r),
        int(base.green() * (1 - r) + tint.green() * r),
        int(base.blue() * (1 - r) + tint.blue() * r),
    )


def _meta_text(value) -> str:
    """Render a metadata value as display text.

    `QMediaMetaData` does not hand back a plain string for every key: the artist
    comes back as a **list** even when there is only one of them (Qt splits the
    tag on its separator), so `str(value)` renders as `['7opy/BT07']` -- the
    list's repr, brackets and quotes included. That is what showed up in the
    artist line.

    Lists are joined with ", " so a genuinely multi-valued tag reads as
    "A, B" instead of "['A', 'B']"; anything else falls back to `str()`.
    """
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


# Background visualisations offered by the 可视化效果 panel, as (label, key)
# pairs. Order is the order in the panel; the first one is the default.
#   checker - the music-reactive perspective checkerboard (the original page)
#   colors  - the album cover as a backdrop, with glassy drifting shapes and
#             blurred light beams over it and a frosted sheet in front
_VISUALIZER_CHECKER = "checker"
_VISUALIZER_COLORS = "colors"
_VISUALIZER_ITEMS = [
    ("棋盘格", _VISUALIZER_CHECKER),
    ("音乐色彩", _VISUALIZER_COLORS),
]
_VISUALIZER_DEFAULT = _VISUALIZER_ITEMS[0][1]
_VISUALIZER_KEYS = tuple(key for _label, key in _VISUALIZER_ITEMS)
# Qt's QWIDGETSIZE_MAX ("no maximum"), which PySide6 does not export.
_MAX_WIDGET_SIZE = 16777215

# The two 音乐色彩 glass slabs: (centre x, centre y, radius, tilt, spin scale).
# Centres are fractions of the page (both are off it), radius a fraction of the
# shorter side, tilt the slab's fixed starting angle, and the spin scale lets the
# two turn in opposite directions.
#
# Measured off the drawing the user supplied (1536x960 -- the page's own 1.6
# aspect, so its pixels map straight onto page fractions). Its two black discs
# were thresholded, labelled and circle-fitted on their hand-drawn arcs (rms 7.6
# and 5.3 px, which is the roughness of the pen):
#
#   upper-left   centre (0.167 w, 0.157 h)  radius 0.582 x min   crosses the top
#                edge at x = 0.517 w and the left edge at y = 0.674 h
#   lower-right  centre (0.860 w, 0.906 h)  radius 0.368 x min   crosses the right
#                edge at y = 0.614 h and the bottom edge at x = 0.638 w
#
# They are anchored exactly there and never translate, so the frame cuts them the
# way the drawing does; the only motion is the slow turn (COLOR_SHAPE_SPIN_DEG_PER_S).
_COLOR_SLABS = [
    (0.167, 0.157, 0.582, 8.0, 1.0),
    (0.860, 0.906, 0.368, -12.0, -1.0),
]
# The school of bubbles: (centre x, centre y, radius). Same units as the slabs,
# and again read straight off the drawing's blue marks (their area turned into an
# equivalent radius). The drawing has eight: six of them land in the 0.03-0.045 x w
# the brief asked for, and the two at the top (0.89 w, 0.17 h) and (0.64 w, 0.19 h)
# are a little smaller -- the second is one bubble that a strand crosses, which is
# why a pixel count alone sees it as two blobs. They never leave the clear band
# between the slabs: the band is what the drawing shows them swimming in, and
# _color_bubble_placements enforces it.
_COLOR_BUBBLES = [
    (0.082, 0.884, 0.064),
    (0.294, 0.848, 0.055),
    (0.705, 0.394, 0.055),
    (0.482, 0.942, 0.053),
    (0.912, 0.406, 0.051),
    (0.526, 0.593, 0.050),
    (0.889, 0.169, 0.039),
    (0.640, 0.187, 0.045),
]


# The face the music menu's items are drawn in.
#
# Held here rather than inherited so the menu keeps the look it was given. Its
# stylesheet sets a font SIZE, and Qt applies stylesheet font properties over the
# widget's own font -- with no family in the rule, the family comes from the
# application font. That is how switching the app-wide interface face silently
# restyled this menu as a side effect.
#
# Change this one string to move the menu between faces:
#   "Microsoft YaHei UI"  -- the Windows UI face, thicker Chinese strokes (current)
#   "Noto Sans SC"        -- sets a little wider, which reads as airier
#
# The two are close here: at the menu's 13 px the stem difference is around half a
# device pixel, so what actually shows is the spacing, not the weight. Both were put
# on screen and the YaHei setting was preferred.
MENU_FONT_FAMILY = "Microsoft YaHei UI"


class _MusicMenu(QWidget):
    """Popup menu for the music player with frosted-glass styling."""

    item_clicked = Signal(int)

    _ITEMS = [
        ("播放列表", "playlist"),
        ("音效设置", "equalizer"),
        ("播放模式", "play_mode"),
        ("定时关闭", "sleep_timer"),
        ("可视化效果", "visualizer"),
        ("设定音乐文件夹", "set_folder"),
    ]

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFont(ui_font())
        self.setMouseTracking(True)
        # font-family is spelled out even though the widget font already carries it:
        # Qt applies a stylesheet's font properties over the widget's own, and a rule
        # that sets only a size inherits the family from the APPLICATION font instead.
        # That made the menu's face follow the app-wide family rather than this
        # widget's, so switching the interface face silently restyled the menu too.
        self.setStyleSheet("""
            _MusicMenu {
                background-color: transparent;
                border: none;
                border-radius: 14px;
            }
            QLabel {
                color: rgba(255, 255, 255, 0.90);
                background: transparent;
                font-family: "%s";
                font-size: 13px;
                padding: 10px 16px;
            }
        """ % MENU_FONT_FAMILY)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        self._labels: list[QLabel] = []
        for i, (title, _) in enumerate(self._ITEMS):
            lbl = QLabel(title)
            lbl.setMouseTracking(True)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.mousePressEvent = lambda _event, idx=i: self.item_clicked.emit(idx)
            lbl.installEventFilter(self)
            layout.addWidget(lbl)
            self._labels.append(lbl)

        self.setFixedWidth(150)
        self.setFixedHeight(self.sizeHint().height())

        # Animated hover highlight that glides between menu items.
        self._hover_index = -1
        self._hover_y = 0.0
        self._hover_vel = 0.0
        self._hover_stretch = 0.0
        self._hover_stretch_vel = 0.0
        self._hover_alpha = 0.0
        self._hover_alpha_vel = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_hover_physics)
        self._timer.start(16)

    def item_data(self, index: int) -> str:
        return self._ITEMS[index][1]

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Swallow presses that land on the popup itself -- its 8 px padding, or
        # the 2 px gaps between rows. Un-accepted they travel up to the page,
        # whose press handler then hit-tests them against whatever sits under
        # the menu: the transport row, this menu's own button, the volume bar.
        event.accept()

    def eventFilter(self, watched, event) -> bool:
        """Forward mouse moves from child labels so fast slides don't lose tracking."""
        if event.type() == event.Type.MouseMove:
            self._update_hover_from_global(event.globalPosition().toPoint())
            self.update()
            return False
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._update_hover_from_local(event.position().toPoint())
        self.update()
        super().mouseMoveEvent(event)

    def _update_hover_from_local(self, pos: QPoint) -> None:
        # Don't clear hover when the cursor is merely between two labels
        # (over layout spacing); only set it when we're truly on an item.
        if not self.rect().contains(pos):
            return
        for i, lbl in enumerate(self._labels):
            if lbl.geometry().contains(pos):
                self._hover_index = i
                return

    def _update_hover_from_global(self, global_pos: QPoint) -> None:
        self._update_hover_from_local(self.mapFromGlobal(global_pos))

    def leaveEvent(self, event) -> None:  # noqa: N802
        # Only clear hover if the mouse is truly outside the menu geometry.
        if not self.rect().contains(self.mapFromGlobal(self.cursor().pos())):
            self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        self._hover_y = 0.0
        self._hover_vel = 0.0
        self._hover_stretch = 0.0
        self._hover_stretch_vel = 0.0
        self._hover_alpha = 0.0
        self._hover_alpha_vel = 0.0
        super().hideEvent(event)

    def _update_hover_physics(self) -> None:
        """Spring-damp the highlight position/opacity/stretch for a trailing glide."""
        target_y = self._target_hover_y()
        if target_y is None:
            target_alpha = 0.0
            target_y = self._hover_y  # keep current y while fading out
        else:
            target_alpha = 1.0

        # Position spring: slightly slower for a smoother, more deliberate glide.
        stiffness = 0.13
        damping = 0.42
        self._hover_vel += (target_y - self._hover_y) * stiffness - self._hover_vel * damping
        self._hover_y += self._hover_vel

        # Stretch spring: gentle elongation in the direction of travel.
        stretch_target = self._hover_vel * 1.2 + (target_y - self._hover_y) * 0.18
        stretch_stiffness = 0.12
        stretch_damping = 0.35
        self._hover_stretch_vel += (stretch_target - self._hover_stretch) * stretch_stiffness - self._hover_stretch_vel * stretch_damping
        self._hover_stretch += self._hover_stretch_vel
        # Clamp to keep the highlight from distorting too much.
        max_stretch = (self._labels[0].geometry().height() if self._labels else 26) * 0.9
        self._hover_stretch = max(-max_stretch, min(max_stretch, self._hover_stretch))

        # Edge bounce: when the stretched highlight would hit the 8 px content
        # margin, give it a little wall kick so it feels like it smacked the edge.
        if self._labels and target_y is not None:
            item_h = self._labels[0].geometry().height()
            highlight_h = max(22, item_h - 2)
            stretch = self._hover_stretch
            if stretch >= 0:
                top = self._hover_y - highlight_h / 2.0
                bottom = self._hover_y + highlight_h / 2.0 + stretch
            else:
                top = self._hover_y - highlight_h / 2.0 + stretch
                bottom = self._hover_y + highlight_h / 2.0
            top_limit = 8
            bottom_limit = self.height() - 8
            if top < top_limit:
                penetration = top_limit - top
                self._hover_vel += penetration * 0.18
                self._hover_stretch_vel += penetration * 0.12
            elif bottom > bottom_limit:
                penetration = bottom - bottom_limit
                self._hover_vel -= penetration * 0.18
                self._hover_stretch_vel -= penetration * 0.12

        # Opacity spring: fades in/out gently.
        alpha_stiffness = 0.18
        alpha_damping = 0.38
        self._hover_alpha_vel += (target_alpha - self._hover_alpha) * alpha_stiffness - self._hover_alpha_vel * alpha_damping
        self._hover_alpha += self._hover_alpha_vel
        self._hover_alpha = max(0.0, min(1.0, self._hover_alpha))

        self.update()

    def _target_hover_y(self) -> float | None:
        if self._hover_index < 0 or self._hover_index >= len(self._labels):
            return None
        geo = self._labels[self._hover_index].geometry()
        return geo.top() + geo.height() / 2.0

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw a rounded frosted-glass background, border and gliding highlight."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 14, 14)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(32, 34, 40, 245))
        painter.drawPath(path)

        border_pen = QPen(QColor(255, 255, 255, 30))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Gliding hover highlight: a spring-followed block that stretches
        # in the direction of movement, as if the previous item is pulling it.
        if self._hover_alpha > 0.01 and self._labels:
            target_y = self._target_hover_y()
            if target_y is not None:
                item_h = self._labels[0].geometry().height()
                highlight_h = max(22, item_h - 2)
                margin = 6
                x = margin
                w = self.width() - margin * 2

                stretch = self._hover_stretch
                # stretch > 0 -> pulled downward, elongate bottom.
                # stretch < 0 -> pulled upward, elongate top.
                y = self._hover_y - highlight_h / 2.0 - max(0.0, stretch) * 0.5
                draw_h = highlight_h + abs(stretch)

                # Clamp to the content area so the highlight never overshoots
                # the menu edges, even when stretched.
                top_limit = 8
                bottom_limit = self.height() - 8
                top = max(top_limit, y)
                bottom = min(bottom_limit, y + draw_h)
                if bottom - top < 4:
                    bottom = top + 4
                y = top
                draw_h = bottom - top

                alpha = int(45 * self._hover_alpha)
                highlight_rect = QRectF(x, y, w, draw_h)

                # Fill.
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(118, 185, 0, alpha))
                painter.drawRoundedRect(highlight_rect, 8, 8)

                # Subtle outline for definition.
                outline_pen = QPen(QColor(160, 220, 70, int(180 * self._hover_alpha)))
                outline_pen.setWidth(1)
                painter.setPen(outline_pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(highlight_rect, 8, 8)


class _ScrollingLabel(QLabel):
    """A single-line label that scrolls long text horizontally instead of overflowing."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self._offset = 0
        self._text_width = 0
        self._scrollable_width = 0
        self._needs_scroll = False
        self._pause_frames = 0

        self.setWordWrap(False)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFont(ui_font())
        self.setStyleSheet("""
            _ScrollingLabel {
                color: rgba(255, 255, 255, 0.85);
                background: transparent;
                font-size: 13px;
                margin: 0px;
                border-radius: 8px;
                padding: 0px;
            }
        """)
        self.setFixedHeight(self.fontMetrics().height() + 16)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(30)

    def _text_left_padding(self) -> int:
        """Horizontal inset that keeps text aligned with the old padded look."""
        return 10

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        super().setText(text)
        self._offset = 0
        self._recalc()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._recalc()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self._recalc()
        self._timer.start(30)
        super().showEvent(event)

    def _recalc(self) -> None:
        self._text_width = self.fontMetrics().horizontalAdvance(self._full_text)
        # Keep the same left/right padding as non-scrolling labels.
        pad = self._text_left_padding()
        available = self.contentsRect().width() - pad * 2
        self._needs_scroll = self._text_width > available + 2
        self._scrollable_width = max(0, self._text_width - available)
        if not self._needs_scroll:
            self._offset = 0
        self.update()

    def _step(self) -> None:
        if not self._needs_scroll or self._scrollable_width <= 0:
            return
        if self._pause_frames > 0:
            self._pause_frames -= 1
            return
        self._offset += 1
        # Pause briefly at the end, then jump back to the start.
        if self._offset >= self._scrollable_width + 20:
            self._offset = 0
            self._pause_frames = 45
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setPen(self.palette().color(self.foregroundRole()))

        rect = self.contentsRect()
        pad = self._text_left_padding()
        # Clip to an inner rectangle so scrolling text never kisses the edges.
        painter.setClipRect(rect.adjusted(pad, 0, -pad, 0))

        fm = self.fontMetrics()
        y = (rect.top() + rect.bottom() + fm.ascent() - fm.descent()) // 2
        painter.drawText(
            int(rect.left() + pad - self._offset),
            int(y),
            self._full_text,
        )


class _PlaylistItemList(QWidget):
    """Scrollable list of rows with the same springy hover highlight as the music menu.

    Rows are virtualised: a small pool of row widgets is repositioned and
    retitled as the view scrolls, so building or filtering a playlist of any
    size costs nothing beyond the rows actually on screen.

    Also backs the 可视化效果 panel, which feeds it ready-made labels through
    `set_labels` instead of song paths -- the highlight then rests on the
    current choice exactly as it rests on the current song here.
    """

    song_selected = Signal(int)

    ROW_GAP = 2
    POOL_SIZE = 26  # materialised rows (the viewport shows ~9)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFont(ui_font())
        self.setMouseTracking(True)
        self.setStyleSheet("""
            _PlaylistItemList {
                background-color: transparent;
                border: none;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Row metrics; rows are absolutely positioned inside this widget.
        self._row_h = QFontMetrics(ui_font(13)).height() + 16
        self._stride = self._row_h + self.ROW_GAP

        # Full playlist (never rebuilt for filtering) and the filtered view.
        self._songs: list[str] = []
        self._titles: list[str] = []
        self._titles_lower: list[str] = []
        # Bumped whenever the titles change, so pooled rows know their cached
        # text is stale (see _sync_pool).
        self._generation = 0
        self._synced_generation = -1  # revision the materialised rows show
        self._visible_rows: list[int] = []
        self._query = ""
        self._current_index = -1
        self._hover_index = -1
        self._first_row = -1  # first row position currently materialised
        self._vbar = None  # cached scroll bar of the surrounding QScrollArea
        # Rows show the full text on hover unless the settings page turns that
        # off (see `set_row_tooltips`).
        self._row_tooltips = True

        # Same spring-damped hover highlight state as _MusicMenu.
        self._hover_y = 0.0
        self._hover_vel = 0.0
        self._hover_stretch = 0.0
        self._hover_stretch_vel = 0.0
        self._hover_alpha = 0.0
        self._hover_alpha_vel = 0.0

        # A small pool of reused row widgets: only the rows near the viewport
        # exist, so building/filtering a huge playlist costs nothing.
        # Row widgets are created on first use: a startup with an empty
        # playlist then costs nothing.
        self._pool: list[_ScrollingLabel] = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_hover_physics)
        self._timer.start(16)

    # ------------------------------------------------------------------
    # Playlist / filtering
    # ------------------------------------------------------------------
    def set_songs(self, songs: list[str], current_index: int = -1) -> None:
        """Populate the list and mark the current song.

        Never scrolls: this is called again every time the user picks a song (the
        load path keeps the panel in sync), and scrolling there made the list jump
        under the cursor as if it had been refreshed. Opening the panel is what
        scrolls the current song into view.
        """
        self._current_index = current_index

        if songs != self._songs:
            self._songs = list(songs)
            self._titles = [
                os.path.splitext(os.path.basename(path))[0] for path in self._songs
            ]
            self._titles_lower = [title.lower() for title in self._titles]
            # Rows cache their text and are only re-labelled when the row they
            # show changes; without this a new playlist of the same length kept
            # the previous folder's names (the count updated, the names did not).
            self._generation += 1

        # Re-apply the active search instead of dropping it on a playlist change.
        self._rebuild_view(snap_highlight=True)

    def set_labels(self, labels: list[str], current_index: int = -1) -> None:
        """Populate the list with ready-made row labels.

        Unlike `set_songs` these are not file paths, so nothing may be stripped
        off them; everything else -- rows, highlight, click handling -- is the
        same list. Like `set_songs`, it leaves the scroll alone.
        """
        self._current_index = current_index
        titles = [str(label) for label in labels]
        if titles != self._titles:
            self._titles = titles
            self._songs = list(titles)
            self._titles_lower = [title.lower() for title in titles]
            self._generation += 1
        self._rebuild_view(snap_highlight=True)

    def set_row_tooltips(self, enabled: bool) -> None:
        """Show the full row text on hover, or stop showing it at all.

        Rows are pooled and reshuffled as the list scrolls, so the setting is
        kept here and re-applied on every sync; whatever is on screen right now
        is updated immediately.
        """
        self._row_tooltips = bool(enabled)
        for lbl in self._pool:
            lbl.setToolTip(lbl.text() if self._row_tooltips else "")

    def apply_filter(self, query: str) -> None:
        """Show only the rows matching *query*.

        Only the visible index list changes - no row widgets are created or
        destroyed - so typing (and clearing) the search stays instant and
        never flashes, even with thousands of songs.
        """
        query = (query or "").strip().lower()
        if query == self._query:
            return
        self._query = query
        # Searching does recenter: the whole point is to find the current song
        # among the matches, and the list is being reshaped anyway.
        self._rebuild_view(snap_highlight=True, recenter=True)

    def visible_count(self) -> int:
        """Number of rows currently shown (after filtering)."""
        return len(self._visible_rows)

    def current_position(self) -> int:
        """1-based position of the current song among the shown rows (0 = not shown)."""
        try:
            return self._visible_rows.index(self._current_index) + 1
        except ValueError:
            return 0

    def _rebuild_view(self, snap_highlight: bool = False, recenter: bool = False) -> None:
        """Recompute the filtered rows, resize the canvas and sync the pool.

        *recenter* is deliberately off by default: a rebuild caused by picking a
        song (or by the player keeping the panel in sync) must leave the scroll
        where the user left it. Scrolling the current song into view is wanted
        only when the panel opens or a search narrows the list -- otherwise the
        list visibly jumps under the cursor, which reads as "the panel refreshed
        itself" even though nothing changed.
        """
        if self._query:
            self._visible_rows = [
                i
                for i, title in enumerate(self._titles_lower)
                if self._query in title
            ]
        else:
            self._visible_rows = list(range(len(self._songs)))

        self.setFixedHeight(max(1, len(self._visible_rows) * self._stride))
        if self._hover_index >= len(self._visible_rows):
            self._hover_index = -1
        if snap_highlight:
            self._snap_highlight()
        if recenter:
            self.scroll_to_current(sync=False)
        self._sync_pool(force=True)
        self.update()

    def _snap_highlight(self) -> None:
        """Jump the highlight straight to its target (no glide) after a change."""
        target = self._target_hover_y()
        if target is not None:
            self._hover_y = target
            self._hover_vel = 0.0
            self._hover_alpha = 1.0
        else:
            self._hover_alpha = 0.0
        self._hover_stretch = 0.0
        self._hover_stretch_vel = 0.0

    def _visible_positions(self) -> list[int]:
        return self._visible_rows

    def _scroller(self):
        """Return the surrounding QScrollArea (looked up once)."""
        if self._vbar is not None:
            return self._vbar
        area = self.parentWidget()
        while area and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is None:
            return None
        self._vbar = area.verticalScrollBar()
        return self._vbar

    def _ensure_pool(self) -> None:
        """Create the reusable row widgets once there is something to show."""
        if self._pool:
            return
        for k in range(self.POOL_SIZE):
            # Parent them immediately: without a parent they would become
            # top-level windows instead of rows inside the list.
            lbl = _ScrollingLabel("", self)
            lbl.setFixedHeight(self._row_h)
            lbl.setMouseTracking(True)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.installEventFilter(self)
            lbl.mousePressEvent = lambda _event, pos=k: self._on_pool_clicked(pos)
            lbl._row_index = -1  # playlist index currently shown in this slot
            lbl._generation = -1  # playlist revision this slot's text came from
            lbl.hide()
            self._pool.append(lbl)

    def _sync_pool(self, force: bool = False) -> None:
        """Materialise the rows around the current scroll position."""
        if self._visible_rows:
            self._ensure_pool()
        total = len(self._visible_rows)
        bar = self._scroller()
        if total == 0 or bar is None or self._stride <= 0:
            if force and total == 0:
                for lbl in self._pool:
                    lbl.hide()
                self._first_row = 0
            return

        first = int(bar.value() / self._stride)
        first = max(0, min(first, max(0, total - len(self._pool))))
        # A new playlist can land on the same first row, so the position alone
        # does not mean the materialised rows are still correct: rows cache both
        # the row they show and which playlist revision they were labelled from.
        stale = force or self._generation != self._synced_generation
        if not stale and first == self._first_row:
            return
        self._first_row = first
        self._synced_generation = self._generation

        for k, lbl in enumerate(self._pool):
            pos = first + k
            if pos >= total:
                lbl._row_index = -1
                lbl._generation = -1
                lbl.hide()
                continue
            idx = self._visible_rows[pos]
            if lbl._row_index != idx or lbl._generation != self._generation:
                lbl._row_index = idx
                lbl._generation = self._generation
                lbl.setText(self._titles[idx])
                lbl.setToolTip(self._titles[idx] if self._row_tooltips else "")
            lbl.setGeometry(0, pos * self._stride, self.width(), self._row_h)
            lbl.show()

    def _on_pool_clicked(self, pool_pos: int) -> None:
        pos = self._first_row + pool_pos
        if 0 <= pos < len(self._visible_rows):
            self._current_index = self._visible_rows[pos]
            self.song_selected.emit(self._current_index)

    def scroll_to_current(self, sync: bool = True) -> None:
        """Scroll so the current song is roughly centered in the viewport."""
        if self._current_index not in self._visible_rows:
            if sync:
                self._sync_pool()
            return
        pos = self._visible_rows.index(self._current_index)
        bar = self._scroller()
        if bar is not None:
            viewport_h = bar.parentWidget().height() if bar.parentWidget() else 0
            target = pos * self._stride - (viewport_h - self._row_h) / 2.0
            bar.setValue(int(max(0, min(bar.maximum(), target))))
        if sync:
            self._sync_pool(force=True)
            self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_pool(force=True)

    def eventFilter(self, watched, event) -> bool:
        """Forward mouse moves from child labels so fast slides don't lose tracking."""
        if event.type() == event.Type.MouseMove:
            self._update_hover_from_global(event.globalPosition().toPoint())
            self.update()
            return False
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._update_hover_from_local(event.position().toPoint())
        self.update()
        super().mouseMoveEvent(event)

    def _update_hover_from_local(self, pos: QPoint) -> None:
        if not self.rect().contains(pos):
            return
        # Only materialised rows can be hovered; translate the pool slot back
        # to its position in the filtered view.
        for k, lbl in enumerate(self._pool):
            if lbl.isVisible() and lbl.geometry().contains(pos):
                self._hover_index = self._first_row + k
                return

    def _update_hover_from_global(self, global_pos: QPoint) -> None:
        self._update_hover_from_local(self.mapFromGlobal(global_pos))

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self.rect().contains(self.mapFromGlobal(self.cursor().pos())):
            self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        self._hover_vel = 0.0
        self._hover_stretch = 0.0
        self._hover_stretch_vel = 0.0
        self._hover_alpha = 0.0
        self._hover_alpha_vel = 0.0
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        target = self._target_hover_y()
        if target is not None:
            self._hover_y = target
            self._hover_vel = 0.0
            self._hover_alpha = 1.0
        super().showEvent(event)

    def _update_hover_physics(self) -> None:
        """Spring-damp the highlight position/opacity/stretch for a trailing glide."""
        # Cheap poll: re-materialise rows when the view has scrolled.
        self._sync_pool()

        target_y = self._target_hover_y()
        if target_y is None:
            target_alpha = 0.0
            target_y = self._hover_y  # keep current y while fading out
        else:
            target_alpha = 1.0

        stiffness = 0.13
        damping = 0.42
        self._hover_vel += (target_y - self._hover_y) * stiffness - self._hover_vel * damping
        self._hover_y += self._hover_vel

        stretch_target = self._hover_vel * 1.2 + (target_y - self._hover_y) * 0.18
        stretch_stiffness = 0.12
        stretch_damping = 0.35
        self._hover_stretch_vel += (stretch_target - self._hover_stretch) * stretch_stiffness - self._hover_stretch_vel * stretch_damping
        self._hover_stretch += self._hover_stretch_vel
        max_stretch = self._row_h * 0.9
        self._hover_stretch = max(-max_stretch, min(max_stretch, self._hover_stretch))

        if self._visible_rows and target_y is not None:
            item_h = self._row_h
            highlight_h = max(22, item_h - 2)
            stretch = self._hover_stretch
            if stretch >= 0:
                top = self._hover_y - highlight_h / 2.0
                bottom = self._hover_y + highlight_h / 2.0 + stretch
            else:
                top = self._hover_y - highlight_h / 2.0 + stretch
                bottom = self._hover_y + highlight_h / 2.0
            top_limit = 4
            bottom_limit = self.height() - 4
            if top < top_limit:
                penetration = top_limit - top
                self._hover_vel += penetration * 0.18
                self._hover_stretch_vel += penetration * 0.12
            elif bottom > bottom_limit:
                penetration = bottom - bottom_limit
                self._hover_vel -= penetration * 0.18
                self._hover_stretch_vel -= penetration * 0.12

        alpha_stiffness = 0.18
        alpha_damping = 0.38
        self._hover_alpha_vel += (target_alpha - self._hover_alpha) * alpha_stiffness - self._hover_alpha_vel * alpha_damping
        self._hover_alpha += self._hover_alpha_vel
        self._hover_alpha = max(0.0, min(1.0, self._hover_alpha))

        self.update()

    def _target_hover_y(self) -> float | None:
        """Y center of the hovered row, falling back to the current song's row."""
        pos = self._target_row_pos()
        if pos is None:
            return None
        return pos * self._stride + self._row_h / 2.0

    def _target_row_pos(self) -> int | None:
        """Position (within the filtered view) the highlight should sit on."""
        total = len(self._visible_rows)
        if total == 0:
            return None
        if 0 <= self._hover_index < total:
            return self._hover_index
        if self._current_index in self._visible_rows:
            return self._visible_rows.index(self._current_index)
        return None

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw the gliding spring highlight (background is painted by the parent panel)."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        row_h = self._row_h if self._visible_rows else 0.0
        if self._hover_alpha > 0.01 and row_h > 0:
            target_y = self._target_hover_y()
            if target_y is not None:
                item_h = row_h
                highlight_h = max(22, item_h - 2)
                margin = 2
                x = margin
                w = self.width() - margin * 2

                stretch = self._hover_stretch
                y = self._hover_y - highlight_h / 2.0 - max(0.0, stretch) * 0.5
                draw_h = highlight_h + abs(stretch)

                top_limit = 4
                bottom_limit = self.height() - 4
                top = max(top_limit, y)
                bottom = min(bottom_limit, y + draw_h)
                if bottom - top < 4:
                    bottom = top + 4
                y = top
                draw_h = bottom - top

                alpha = int(45 * self._hover_alpha)
                highlight_rect = QRectF(x, y, w, draw_h)

                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(118, 185, 0, alpha))
                painter.drawRoundedRect(highlight_rect, 8, 8)

                outline_pen = QPen(QColor(160, 220, 70, int(180 * self._hover_alpha)))
                outline_pen.setWidth(1)
                painter.setPen(outline_pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(highlight_rect, 8, 8)


class _FrostedPanel(QWidget):
    """Body shared by the popup panels: rounded frosted glass, presses swallowed.

    Swallowing matters. An un-accepted press travels up to the page, whose press
    handler treats it as a click outside the popup -- and then hit-tests it
    against whatever sits under the popup, so clicking a panel's padding or
    title could press a transport button behind it.

    It also owns the size rules that make a panel unfold out of the folder
    button: see `begin_popup_animation`.
    """

    CORNER_RADIUS = 14
    # Size the panel settles into, as (width, height). A height of None means the
    # height follows the content instead of being fixed (the effect panel).
    RESTING_SIZE = (240, None)
    # How far into the unfold the header reaches full height, as a fraction of the
    # panel's growth. Measured off the effect panel, whose height-locked list left
    # the layout no choice but to squeeze its title: 12 px -> 0 -> 7 -> 12 over the
    # first 64 ms, i.e. full height at ~71% of the way.
    HEADER_REVEAL_PROGRESS = 0.71

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        # (label, full height) pairs taking part in the header squeeze, and the
        # height the unfold starts from (both set up by begin_popup_animation).
        self._header_labels: list[tuple[QLabel, int]] = []
        self._popup_start_height = 1

    def resting_height(self) -> int:
        """Height the panel settles at."""
        height = self.RESTING_SIZE[1]
        return self._content_height if height is None else height

    def set_row_tooltips(self, enabled: bool) -> None:
        """Show the row labels' hover text, or stop showing it (settings switch)."""
        self._list.set_row_tooltips(enabled)

    def register_header_label(self, label: QLabel) -> None:
        """Let a header label take part in the unfold's squeeze (see resizeEvent)."""
        self._header_labels.append((label, label.sizeHint().height()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._squeeze_header()

    def _squeeze_header(self) -> None:
        """Squeeze the header in proportion to how far the unfold has come.

        This is the little jitter the effect panel used to get for free: its list
        has a fixed height, so while the panel was too short the layout had nowhere
        to take the deficit but the title. The playlist's list is elastic and
        swallowed all of it, so its title never deformed -- which is exactly where
        the two unfolds looked different. Driving the squeeze from the unfold's
        PROGRESS (not from raw pixels) puts both panels on the same clock: they
        reach the same fraction of their growth at the same moment, so the title
        springs back together, which is what the effect panel already did.
        """
        span = max(1, self.resting_height() - self._popup_start_height)
        progress = (self.height() - self._popup_start_height) / span
        revealed = max(0.0, min(1.0, progress / self.HEADER_REVEAL_PROGRESS))
        for label, full_height in self._header_labels:
            label.setMaximumHeight(round(full_height * revealed))

    def begin_popup_animation(self, start_height: int) -> None:
        """Free the height so the popup animation can really unfold the panel.

        The width stays pinned, so the panel keeps its footprint. With the
        height pinned as well (setFixedSize), QWidget.setGeometry() is clamped
        to the resting size and the animation can only SLIDE the panel across
        the page at full size -- which is what the playlist panel used to do,
        while the effect panel really grew out of the button. Freeing the height
        is what makes the two popups behave the same.
        """
        self._popup_start_height = max(1, start_height)
        self.setMinimumHeight(0)
        self.setMaximumHeight(_MAX_WIDGET_SIZE)

    def end_popup_animation(self) -> None:
        """Put the resting size back once the animation is over."""
        width, height = self.RESTING_SIZE
        if height is None:
            self.setFixedWidth(width)
        else:
            self.setFixedSize(width, height)
        for label, _full_height in self._header_labels:
            label.setMaximumHeight(_MAX_WIDGET_SIZE)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw a rounded frosted-glass background and border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(rect), self.CORNER_RADIUS, self.CORNER_RADIUS
        )

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(32, 34, 40, 245))
        painter.drawPath(path)

        border_pen = QPen(QColor(255, 255, 255, 30))
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


# Shared stylesheet for the two popup panels (playlist + visualizer). The frosted
# body is painted by `_FrostedPanel`, so a panel's own rule only has to clear
# Qt's background.
#
# The QToolTip rule used to be repeated here. It now lives in constants.TOOLTIP_STYLE
# and is installed once on the QApplication, because Qt resolves a tip's style from
# the widget showing it, from its parent, or from the application (all three
# measured to work) -- and with none of them the tip text falls back to the
# palette's black, which is invisible on these dark panels. That is exactly how the
# visualizer once ended up black-on-black after being copied from the playlist
# without the block. Application level means a new panel cannot forget it again.
_POPUP_PANEL_STYLE = """
    %s {
        background-color: transparent;
        border: none;
        border-radius: 14px;
    }
"""


class _PlaylistPanel(_FrostedPanel):
    """Popup playlist panel with frosted-glass styling and a springy song highlight."""

    song_selected = Signal(int)

    WIDTH = 240
    HEIGHT = 320
    RESTING_SIZE = (WIDTH, HEIGHT)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFont(ui_font())
        self.setStyleSheet(_POPUP_PANEL_STYLE % "_PlaylistPanel")

        layout = QVBoxLayout(self)
        # Top margin one pixel tighter, with the two text lines padded back
        # down by the same amount: the search box (which is clamped to the top
        # of its grid cell) ends up exactly 1 px higher while the title and the
        # count stay where they were.
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(4)

        # Title (raised and nudged left) with the "position/total" count right
        # under it, and the search box pushed to the right edge.
        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(6)
        header.setVerticalSpacing(1)

        self._title_label = QLabel("播放列表")
        self._title_label.setStyleSheet(
            "color: rgba(255,255,255,0.55); font-size: 11px; padding: 1px 0px 0px 2px;"
        )
        header.addWidget(
            self._title_label, 0, 0, Qt.AlignLeft | Qt.AlignTop
        )
        self.register_header_label(self._title_label)

        # "25/233" = the 25th song of 233 in the list; no label text.
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(
            "color: rgba(255,255,255,0.38); font-size: 10px; padding: 1px 0px 0px 2px;"
        )
        header.addWidget(
            self._count_label, 1, 0, Qt.AlignLeft | Qt.AlignTop
        )
        self.register_header_label(self._count_label)
        header.setColumnStretch(0, 1)

        self._search = QLineEdit(self)
        self._search.setFont(ui_font(11))
        self._search.setPlaceholderText("搜索")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedSize(104, 25)
        self._search.setFocusPolicy(Qt.StrongFocus)
        # No vertical padding: the text is centred in the capsule.
        self._search.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 12px;
                color: rgba(255, 255, 255, 0.88);
                font-size: 11px;
                padding: 0px 8px;
                selection-background-color: #76B900;
            }
            QLineEdit:hover {
                background: rgba(255, 255, 255, 0.12);
            }
            QLineEdit:focus {
                background: rgba(255, 255, 255, 0.14);
                border: 1px solid rgba(160, 220, 70, 0.60);
            }
        """)
        self._search.textChanged.connect(self._apply_filter)
        # Wrapped with a 2 px bottom margin so it sits 1 px above the centre of
        # the two header rows; shifting the wrapper leaves the title and the
        # count line untouched.
        search_holder = QWidget()
        search_layout = QVBoxLayout(search_holder)
        search_layout.setContentsMargins(0, 0, 0, 2)
        search_layout.setSpacing(0)
        search_layout.addWidget(self._search)
        header.addWidget(
            search_holder, 0, 1, 2, 1, Qt.AlignRight | Qt.AlignVCenter
        )
        layout.addLayout(header)

        self._list = _PlaylistItemList()
        # The list emits real playlist indices, so no remapping is needed.
        self._list.song_selected.connect(self._on_song_selected)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        # Keep the viewport from filling with the palette base color (white in
        # the light palette) for a frame while the list re-lays out.
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._scroll.setWidget(self._list)
        layout.addWidget(self._scroll)

        self.setFixedSize(self.WIDTH, self.HEIGHT)

    def set_songs(self, songs: list[str], current_index: int = -1) -> None:
        """Populate the list with song titles and highlight the current one."""
        self._list.set_songs(songs, current_index)
        # Keep the active search applied to the new playlist.
        self._list.apply_filter(self._search.text())
        self._update_count()

    def scroll_to_current(self) -> None:
        """Bring the playing song into view.

        Separate from `set_songs` on purpose: the list is repopulated every time a
        song is picked, and scrolling then made it look like the whole panel had
        refreshed itself. Opening the panel is the moment this is wanted.
        """
        self._list.scroll_to_current()

    def _apply_filter(self, *_args) -> None:
        """Forward the search text to the list, which toggles row visibility."""
        self._list.apply_filter(self._search.text())
        self._update_count()

    def _on_song_selected(self, index: int) -> None:
        self._update_count()
        self.song_selected.emit(index)

    def _update_count(self) -> None:
        """Show "position/total" for the rows currently listed."""
        total = self._list.visible_count()
        if total == 0:
            self._count_label.setText("")
            return
        position = self._list.current_position()
        self._count_label.setText(
            f"{position}/{total}" if position else f"—/{total}"
        )


class _VisualizerPanel(_FrostedPanel):
    """Popup panel listing the background visualisations.

    A sibling of `_PlaylistPanel` on purpose: same frosted body, same title line
    over the list, same row highlight (which rests on the current effect the way
    it rests on the current song), popped out of the folder button by the same
    animation. The only difference is height, which follows its short list
    instead of the playlist's fixed 320 px.
    """

    effect_selected = Signal(int)

    WIDTH = 240
    # Height follows the effect list (see `set_effects`), so only the width is
    # pinned -- which is also what lets this panel unfold during the popup
    # animation.
    RESTING_SIZE = (WIDTH, None)
    # Never taller than the playlist panel, however many effects are added.
    MAX_LIST_HEIGHT = 260
    TITLE = "可视化效果"

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFont(ui_font())
        self.setStyleSheet(_POPUP_PANEL_STYLE % "_VisualizerPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(4)

        self._title_label = QLabel(self.TITLE)
        self._title_label.setStyleSheet(
            "color: rgba(255,255,255,0.55); font-size: 11px; padding: 1px 0px 0px 2px;"
        )
        layout.addWidget(self._title_label, 0, Qt.AlignLeft | Qt.AlignTop)
        self.register_header_label(self._title_label)

        self._list = _PlaylistItemList()
        self._list.song_selected.connect(self._on_row_selected)

        # The list finds its scroll area by walking up the parent chain, so it
        # needs one here too -- exactly as in the playlist panel.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._scroll.setWidget(self._list)
        layout.addWidget(self._scroll)

        self.setFixedWidth(self.WIDTH)
        self.set_effects([], -1)

    def set_effects(self, labels: list[str], current_index: int = -1) -> None:
        """Fill the list and shrink the panel to fit it."""
        self._list.set_labels(list(labels), current_index)
        self._scroll.setFixedHeight(
            min(max(1, self._list.height()), self.MAX_LIST_HEIGHT)
        )
        # Height follows the rows; the width stays fixed so the panel keeps the
        # playlist panel's footprint.
        self.layout().activate()
        self.adjustSize()
        # Remembered for `resting_height`, i.e. for the header squeeze.
        self._content_height = self.height()

    def _on_row_selected(self, index: int) -> None:
        self.effect_selected.emit(index)


# Music-reactive checkerboard background tuning.
UI_REF_HEIGHT = 600
LYRICS_ENTRY_GAP = 24
LYRICS_EDGE_MARGIN = 80
# How long a copied lyric line stays lit, and the exponential decay shaping it.
# The flash is gone once it falls below LYRICS_COPY_FLASH_CUTOFF, so the decay
# constant is chosen so the whole thing lands near this nominal duration: with
# tau=115 ms the flash is imperceptible after ~520 ms (measured on rendered
# frames). A longer tau read as a lingering glow rather than a blink.
LYRICS_COPY_FLASH_TAU_MS = 115.0
# Peak of the copied line's flash. At 1.0 the text is solid white, and nothing
# is drawn behind it.
LYRICS_COPY_FLASH_PEAK = 1.0
# Below this the flash is dropped entirely. At 0.002 the boost is under 1 luma
# (measured), so the drop is invisible; cutting at 0.02 instead left the line
# visibly bright and popped.
LYRICS_COPY_FLASH_CUTOFF = 0.002

# Line-change motion.
#
# The whole list used to move as one rigid block: a single scroll offset shared by every line,
# plus an instant font-size jump on the active one. That is why a line change read as a snap --
# nothing in the panel ever overshot or lagged, so there was no sense of weight.
#
# Three motions now combine, each independently switchable so the feel can be tuned by editing
# numbers rather than re-reading the drawing code:
#
#   * per line, a spring offset. The incoming line starts LIFT px below and springs up through
#     zero; the outgoing line is pushed PUSH px up and springs back.
#   * the list's own scroll offset, also spring driven. The old code eased 12% per frame toward
#     the target, which approaches forever and never overshoots: soft arrival, no weight, and a
#     long tail.
#   * a per-line start delay, so the motion travels down the list as a wave instead of arriving
#     everywhere at once. The delay decays to zero over WAVE_SPAN lines; without that decay a
#     thirty-line list would queue up well over a second.
#
# Both springs are described physically: OMEGA is the undamped natural frequency in radians per
# second (higher = faster) and RATIO is the fraction of critical damping (1.0 = fastest arrival
# with no overshoot, lower = bouncier). Keep them physical -- the frame-based recursive form the
# resize spring uses elsewhere in this file takes numbers of a different kind entirely, and
# feeding those to this integrator makes every combination diverge.
# The line that arrives. Tuned for a visible but not showy bounce: this spring overshoots
# about 11% of its travel and reverses twice. Measured, raising the ratio further drops it to
# a single reversal and an overshoot under 2 px, at which point it stops reading as a bounce
# and the line simply arrives.
LYRICS_LINE_SPRING_OMEGA = 22.0
LYRICS_LINE_SPRING_RATIO = 0.55
# The lines that ride along with the ripple. Deliberately not the same spring: at the values
# above they overshot too, so the whole panel wobbled and that competed with the arriving line
# for attention. These arrive with no overshoot and no reversal at all -- the panel settles, and
# the only thing that bounces is the line that just became current.
LYRICS_RIPPLE_SPRING_OMEGA = 26.0
LYRICS_RIPPLE_SPRING_RATIO = 0.9
# How far below its resting place the incoming line starts. Large, because this is the one
# motion that belongs to a single line; everything else moves together.
LYRICS_LINE_LIFT_PX = 28.0
# How far the outgoing line is pushed up. 0 disables the push entirely.
#
# Off by default. The line being left behind already travels one whole row as the list scrolls,
# and that travel is the most legible motion on screen -- a recognisable object moving a full
# row -- so a push only made it louder and made the change read as the OLD line moving. It now
# does nothing of its own beyond the shared scroll.
LYRICS_LINE_PUSH_PX = 0.0
# Delay applied per line of distance from the line that changed.
LYRICS_WAVE_STAGGER_MS = 12.0
# How far the ripple displaces a line before it settles back. Small on purpose: this is the
# secondary motion that makes the change travel down the list, not the movement itself.
LYRICS_WAVE_PX = 16.0
# Distance in lines over which the delay grows to its maximum. Short on purpose: the panel
# should read as one sheet bending, which needs the differential motion concentrated near the
# line that changed. A long span gives every nearby line almost the same delay, so they move as a
# block and the arriving line's rise is lost against them.
LYRICS_WAVE_SPAN = 5.0
# How many lines join the ripple at all. Deliberately larger than the span, and larger than the
# panel can show: when these were one number the ripple stopped partway down and the cut-off was
# visible as a hard edge. The delay stops growing at the span; participation does not.
LYRICS_WAVE_REACH = 40.0
# Spring driving the list's scroll offset. Slightly under critical, so it lands with a hint of
# weight rather than easing in.
#
# Deliberately quicker than the line spring. The scroll is the motion every line performs
# together, and the longer it takes the more the panel appears to be travelling -- which is what
# made the outgoing line look like it was doing something of its own.
LYRICS_SCROLL_SPRING_OMEGA = 24.0
LYRICS_SCROLL_SPRING_RATIO = 0.9
# Below this the spring counts as settled and is dropped from the animation table. Chosen from
# the measured step profile: the incoming line moves about 3 px per frame at the start and less
# than 0.35 px per frame after ~190 ms. Continuing past that adds a crawl nobody can see, which
# makes the motion read as uneven rather than as a smooth decay. Not raised further on purpose:
# cutting while the line is still visibly off its resting place would pop.
LYRICS_SPRING_SETTLE_PX = 0.35
LYRICS_SPRING_SETTLE_V = 0.60
# The arriving line settles on position alone. Its velocity passes through zero at the top of
# the bounce, so any velocity gate tight enough to matter declares it settled at that peak -- and
# for a spring the position threshold already bounds the speed (peak speed is about omega times
# it), so the gate was only ever able to cut the motion short.
#
# The threshold must also be far below how far the spring travels in one frame. Measured, the
# crossing frame takes it from +2.60 px to -0.07 px; at the 0.5 px this started at, that step
# landed inside the threshold, the spring was deleted mid-flight, and the true overshoot of
# -3.02 px was never reached -- the bounce was there in the maths and gone on screen.
LYRICS_BOUNCE_SETTLE_PX = 0.05
# How far into its rise the arriving line reaches full opacity, as a fraction of its travel.
# This is the arrival's signature: the line being left already slides a full row along with
# everything else, which reads as motion but not as an event, while a new line appearing where
# nothing was reads as the event itself. 0 disables it and the line is simply opaque.
LYRICS_ARRIVAL_FADE = 0.6

# How much the non-active lines are shrunk before being scaled back up, when the visualiser is the
# colour one. This is the blur radius: 1 would be no blur at all, and larger values are softer.
# Qt exposes no "blur this pixmap", so shrink-and-grow is the mechanism.
#
# Set high on purpose. Measured at 3.0 -- the first value -- only 16% of the panel changed and the
# words stayed readable: a 37 px line reduced to a third and grown back keeps its letterforms. The
# panel is meant to look like the lyrics dissolved into the background, so the strokes have to go.
#
# Note the returns: averaging a bright stroke over a dark panel can only dilute it so far, so
# raising this past 8 buys very little and the dimming below does the rest of the work.
LYRICS_BLUR_SHRINK = 2.5
# Dimming for the non-active lines under the colour visualiser, applied to the whole layer.
#
# This is what does most of the work, and it is the knob to turn for feel. Measured at 0.65 with a
# blur radius of 8: the brightest pixel of a non-active line sits at about half its unblurred value
# and about a quarter of the active line's -- a visible shape whose words cannot be read. Lower it
# and the lines fade out entirely; raise it and they become legible again. Note that at a high blur
# radius it stops having much effect, because the blur has already spread the ink thin.
# 1.0 disables it.
LYRICS_COLOR_OPACITY = 1.0

# Alpha for a lyric line that is not the active one, and how fast that falls off with distance from
# it. Previously these were literals in the drawing loop -- 190 minus 55 per row, floored at 50 --
# which left the third line out at 50, a fifth of the active line, before any blur.
#
# That was the real reason the other lines could not be seen under the colour visualiser: the blur
# was blamed for it, but a line drawn at alpha 50 has almost nothing left to blur. Raised so the
# nearest lines read clearly and the far ones stay legible; the fade is kept, because a column of
# lines all at the same weight reads as a wall.
# The faded step, used under the colour visualiser. Its own numbers rather than the ones above,
# because they are different brightnesses doing different jobs: these lines are meant to be seen and
# not read, while the ordinary ones are meant to be read. Measured, this pair leaves a non-active line
# at about a fifth of the active line's contrast.
# The fade itself is animated, 0 to 1, where 1 is fully faded and is where it rests. One number for
# the whole panel, so every line moves together, and a spring rather than a ramp so the change has the
# same weight as the rest of the panel's motion.
# How much dimmer the unreached lines are under the colour visualiser with the fade switched off.
# The panel is busy there, so the plain step reads as uniformly bright and the order is lost.
LYRICS_COLOR_IDLE_SCALE = 0.72

# How far beyond the words the hover region reaches, on every side. The air around the band is what
# keeps the effect steady as the pointer crosses its edges.
LYRICS_HOVER_PAD_PX = 8

LYRICS_FADE_SPRING_OMEGA = 7.0
LYRICS_FADE_SPRING_RATIO = 0.9
LYRICS_FADE_SETTLE = 0.004

LYRICS_FADE_ALPHA = 44
LYRICS_FADE_ALPHA_STEP = 3
LYRICS_FADE_ALPHA_MIN = 42
LYRICS_IDLE_ALPHA = 215
LYRICS_IDLE_ALPHA_STEP = 22
LYRICS_IDLE_ALPHA_MIN = 150
# Cache key for the blurred layer. Dropped whenever the text, the geometry or the layer's inputs
# change, which is cheaper than hashing the rendered pixels.
_LYRICS_BLUR_CACHE: dict = {}

# The active line grows from the idle size to this one, driven by the same spring.
LYRICS_FONT_SIZE_IDLE = 17
LYRICS_FONT_SIZE_ACTIVE = 19


_PLACEHOLDER_COVER: QPixmap | None = None


def _get_placeholder_cover() -> QPixmap | None:
    return _PLACEHOLDER_COVER


def _store_placeholder_cover(pixmap: QPixmap) -> None:
    global _PLACEHOLDER_COVER
    _PLACEHOLDER_COVER = pixmap


class ToyPage(QWidget):
    """A music player page over a cover-colored, music-reactive checkerboard."""

    # Emitted only when the USER picks a folder from this page's own picker, so
    # the choice can be persisted and mirrored into the settings page. It is
    # deliberately not emitted for folder loads driven by the settings page --
    # that would bounce the value straight back to its origin.
    music_dir_picked = Signal(str)

    # Emitted when the background visualisation changes, so the window can
    # remember it: the choice lives in this page's own submenu, which has no row
    # on the settings page.
    visualizer_changed = Signal(str)

    # Emitted when the lyric alignment changes (settings row -> this page).
    lyrics_align_changed = Signal(int)
    lyrics_size_changed = Signal(int)
    lyrics_fade_changed = Signal(bool)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Whole page (and its popups) uses the sans-serif music face; child
        # stylesheets that only set a size inherit it.
        self.setFont(ui_font())
        self.setMouseTracking(True)  # hover tracking for vinyl light
        self._mouse = QPointF(0, 0)
        self._mouse_down = False

        # Animation timer.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        # Whether this page is the one on screen (set by show/hide below).
        self._page_visible = False
        # Audio analysis has a second driver. The animation timer stops while the
        # page is hidden, but the rhythm is still wanted then: the dashboard's
        # checker floor borrows it (`music_rhythm`). So while hidden AND playing,
        # this one keeps analysing -- and only this one, so a visible page keeps
        # its original cadence instead of analysing twice per frame.
        self._rhythm_timer = QTimer(self)
        self._rhythm_timer.setInterval(16)
        self._rhythm_timer.timeout.connect(self._rhythm_tick)

        # Player state.
        self._is_playing = False
        self._current_track: str | None = None
        self._progress_slider = ElasticSlider(0.35)
        self._volume_slider = ElasticSlider(0.60)
        self._music_phase = 0.0
        # Real music reactivity: analysed from the PCM around the playhead
        # when the scratch engine is active, synthesised otherwise. Drives
        # the checkerboard brightness, scroll speed and beat flashes.
        self._music_level = 0.0
        self._music_bass = 0.0
        self._target_level = 0.3
        self._target_bass = 0.2
        self._beat_impulse = 0.0
        self._beat_cool = 0.0
        self._beat_avg = 0.15
        self._lvl_peak = 0.12
        self._analyze_frame = 0
        self._music_palette: list[QColor] = []
        # PCM turntable engine preference (set from the settings page).
        self._pcm_enabled = True
        # Checkerboard scroll position, in rows (fractional).
        self._checker_offset = 0.0

        # 音乐色彩 backdrop: three slow clocks (the slabs turning, the bubbles
        # swaying, the beams swaying) plus the cached cover layers (raw backdrop
        # and its frost sheet), keyed by size and palette so they are rebuilt
        # only when either changes.
        self._bubble_clock = 0.0
        self._color_spin = 0.0
        self._color_cache_key = None
        self._color_layers: tuple = (None,)
        # The palette mist's own clock: it is what makes the blobs wander, and it
        # is free because the field is redrawn from scratch anyway (see _color_mist).
        self._color_mist_phase = 0.0
        # Cached grain tile for the 音乐色彩 backdrop.
        self._noise_tile: QPixmap | None = None
        self._noise_offset = QPoint(0, 0)
        self._noise_clock = 0.0
        # The 音乐色彩 composite, rebuilt every COLOR_FRAME_STEP_MS rather than
        # every frame (see _draw_music_colors).
        self._color_frame: QPixmap | None = None
        self._color_frame_key = None
        self._color_frame_clock = 0.0
        # Size the composite currently matches, and how long the size has held
        # still (see _draw_music_colors: a live resize stretches, then rebuilds).
        self._color_size_seen = None
        self._color_settle_clock = 0.0
        self._cover = self._create_placeholder_cover()
        # Which track the pixmap in `_cover` belongs to. Reloading the same file must keep it:
        # Qt does not re-announce metadata for a source it is already playing (measured: zero
        # `metaDataChanged` emissions on a repeat `setSource`), so anything cleared on reload
        # stays cleared.
        self._cover_path: str | None = None
        # Container the file on disk uses, when it differs from the audio the
        # backend actually plays (an unpacked ncm). Shown before the format.
        self._source_label = ""
        # Cover taken from a container that QMediaPlayer cannot read, held so
        # later metadata updates do not replace it with a placeholder.
        self._container_cover = None
        self._music_dir = ""
        self._song_title = ""
        self._song_artist = ""
        self._album = ""
        self._had_lyrics = False
        self._lyrics: list[tuple[float, str]] = []
        self._track_info: dict[str, object] = {}
        # Per-line marquee state for the title / artist+album / spec lines
        # under the cover, keyed by line name. Only lines too wide to fit
        # scroll, and each starts paused so short text never moves.
        self._info_scroll: dict[str, dict[str, float | bool]] = {}

        # Vinyl record state.
        self._vinyl_angle = 0.0
        self._vinyl_dragging = False
        self._vinyl_last_mouse_angle = 0.0
        self._vinyl_angular_velocity = 0.0
        self._vinyl_display_velocity = 0.0  # deg/ms, for sheen & arm feedback
        self._vinyl_out = False
        self._vinyl_out_progress = 0.0
        self._vinyl_out_anim = QPropertyAnimation(
            self, b"vinylOutProgress", self
        )
        self._vinyl_out_anim.setDuration(380)
        self._sleeve_rect = QRect()
        # (size, ratio, cover key) -> sleeve pixmap built at device resolution.
        self._sleeve_cache: tuple | None = None
        self._vinyl_record_center = QPointF()
        self._vinyl_record_radius = 0.0
        self._vinyl_scratch_delta = 0.0
        self._vinyl_scratch_start_angle = 0.0
        self._vinyl_scratch_start_position = 0
        # Unwrapped rotation since the scratch began. `_vinyl_angle` is this
        # reduced to 0-360 for display, but the audio mapping needs full turns.
        self._scratch_rotation_deg = 0.0
        # Playhead captured when the current grab began; the scratch target is
        # measured from here, so it starts equal to the live audio position.
        self._scratch_base_ms = 0.0
        # True only between engaging a scratch and releasing it. A press merely
        # sets `_vinyl_dragging`; the playhead must not be driven until this is
        # set, or the target (still anchored to the previous grab) drags the
        # audio backwards while the hand is just resting on the record.
        self._vinyl_scratch_engaged = False
        self._vinyl_drag_origin = None
        self._vinyl_press_pos = None
        self._vinyl_press_audio_ms = 0
        # Pulling the record out of the sleeve by hand (the mirror of the
        # throw-back gesture).
        self._vinyl_pull_active = False
        self._vinyl_pull_origin = None
        self._vinyl_pull_start_progress = 0.0
        # Pressing the record arms a scratch; moving the pointer engages it, so
        # the throw-back drag never scratches on its way out.
        self._vinyl_scratch_armed = False
        self._vinyl_drag_timer = QElapsedTimer()
        self._vinyl_label_color: QColor | None = None
        self._vinyl_lift = 1.0  # smoothed scratch lift (1.0 = resting)
        self._angle_offset_ms = 0.0  # paused-coast angle, in audio ms
        self._vinyl_pixmap_cache: dict = {}
        self._cursor_shape = None

        # Frame-rate independent animation timing.
        self._tick_elapsed_timer = QElapsedTimer()
        self._tick_elapsed_timer.start()

        # Lyrics panel animation (0 = hidden/full-width player, 1 = half-width player + lyrics).
        self._lyrics_progress = 0.0
        self._lyrics_anim = QPropertyAnimation(self, b"lyricsProgress", self)
        self._lyrics_anim.setDuration(420)

        # Lyrics scrolling / click-to-seek.
        self._lyrics_scroll_offset = 0.0
        # Where the offset is heading. Kept apart from the offset itself because a spring needs
        # a target to accelerate toward, where the old easing read it fresh each frame.
        self._lyrics_scroll_target = 0.0
        # Spring velocity for the offset above, so the list can overshoot slightly.
        self._lyrics_scroll_velocity = 0.0
        # Which line changed last, and when, so the per-line motion can be timed from it.
        self._lyrics_anim_from = -1
        self._lyrics_anim_to = -1
        self._lyrics_active_seen = -1
        # Frame time accumulated since the change, in ms. The same clock the springs use.
        self._lyrics_anim_elapsed = 0.0
        # index -> [offset, velocity] for the lines still moving. Only the handful near the
        # active line ever animate, so this stays tiny; entries are dropped once settled.
        self._lyrics_line_springs: dict[int, list[float]] = {}
        # Where the lines sit in their panel; the settings page changes it.
        self._lyrics_align = DEFAULT_LYRICS_ALIGN
        # How large the lines are: an index into LYRICS_SIZES, which carries the font sizes and
        # the edge margin together (see the note there).
        self._lyrics_size = DEFAULT_LYRICS_SIZE
        # Whether the non-active lines fade under the colour visualiser; the settings page
        # toggles it. Held here rather than checked per paint so the drawing stays a pure read.
        self._lyrics_fade = DEFAULT_LYRICS_FADE
        # Which line the pointer is over, or -1.
        self._lyrics_hover_index = -1
        # How faded the panel is, 0 to 1: 1 is fully faded, which is where it rests, and 0 is the
        # ordinary look. Animated rather than switched, because snapping between the two is abrupt.
        self._lyrics_fade_value = 1.0
        self._lyrics_fade_velocity = 0.0
        # Whether the fade is currently being released by the pointer. Computed by
        # _refresh_lyrics_fade, which the tick calls -- so it has to exist before the first paint,
        # not be introduced by it.
        self._lyrics_fade_lifted = False
        # Memoised lyric heights. The layout asks for every line's wrapped height
        # several times per frame (content height, scroll target, scroll range --
        # measured ~600 calls per 6 frames), and each measurement builds a fresh
        # QFont and shapes the text. That is not just wasteful: for a line full of
        # glyphs no installed font carries -- a lyric like "(˶˃ ᵕ ˂˶) .ᐟ.ᐟ" -- Qt
        # fails to resolve a face, reaches for the bitmap "Fixedsys", prints a
        # DirectWrite warning per FRESH font object, and spends milliseconds doing
        # it, which starved the audio pump sharing this thread: the user heard the
        # music stutter for as long as that line was on screen. Cached, that cost
        # is paid once per layout instead of once per frame. Dropped whenever the
        # lyrics change or the wrapping width changes.
        self._lyric_height_cache: dict[tuple[int, int, bool], int] = {}
        self._lyric_height_width = -1
        self._lyrics_auto_follow = True
        self._lyrics_dragging = False
        self._lyrics_drag_moved = False
        self._lyrics_drag_start_y = 0
        self._lyrics_scroll_at_drag_start = 0.0
        self._lyrics_panel_rect = QRect()
        self._lyrics_hit_rects: list[tuple[QRect, int]] = []
        # The same list, kept from the last completed paint. The live one is empty or partial
        # while a paint is running -- it is cleared on entry and filled in two passes -- so it
        # cannot be consulted mid-draw, which is exactly where the hover test needs it.
        self._lyrics_row_rects: list[tuple[QRect, int]] = []
        # Right-click copies a lyric line; the copied line flashes instead of a
        # toast so nothing covers the words. Progress 1 -> 0, decayed in _tick.
        self._lyric_copy_flash_index = -1
        self._lyric_copy_flash = 0.0
        self._lyrics_resume_timer = QTimer(self)
        self._lyrics_resume_timer.setSingleShot(True)
        self._lyrics_resume_timer.timeout.connect(self._resume_lyrics_auto_follow)

        # Playback.
        self._player = None
        self._audio_output = None
        self._duration = 0
        self._playlist: list[str] = []
        self._playlist_index = -1
        self._setup_player()

        # Speaker icon bounce offsets for the volume bar.
        self._vol_icon_l_offset = 0.0
        self._vol_icon_r_offset = 0.0
        self._vol_icon_l_vel = 0.0
        self._vol_icon_r_vel = 0.0
        # Per-button jelly press feedback, keyed by button kind.
        self._btn_press: dict[str, dict[str, float]] = {}

        # Hit rects for clickable elements (updated each paint).
        self._play_btn_rect = QRect()
        self._prev_btn_rect = QRect()
        self._next_btn_rect = QRect()
        self._folder_btn_rect = QRect()
        self._progress_bar_rect = QRect()
        self._volume_bar_rect = QRect()

        # Music popup menu.
        self._music_menu = _MusicMenu(self)
        self._music_menu.hide()
        self._music_menu.item_clicked.connect(self._on_music_menu_clicked)
        self._menu_anim = QPropertyAnimation(self._music_menu, b"geometry", self)
        self._menu_anim.setDuration(320)
        self._menu_anim.setEasingCurve(QEasingCurve.OutBack)
        self._menu_hide_connected = False

        # Background-visualisation chooser, opened from the menu's 可视化效果
        # row. It is presented exactly like the playlist panel -- menu closes,
        # panel pops out of the folder button -- so it takes the same animation.
        self._visualizer = _VISUALIZER_DEFAULT
        self._visualizer_panel = _VisualizerPanel(self)
        self._visualizer_panel.hide()
        self._visualizer_panel.effect_selected.connect(
            self._on_visualizer_effect_selected
        )
        self._visualizer_anim = QPropertyAnimation(
            self._visualizer_panel, b"geometry", self
        )
        self._visualizer_anim.setDuration(320)
        self._visualizer_anim.setEasingCurve(QEasingCurve.OutBack)
        # One permanent handler instead of connecting/disconnecting hide-on-finish
        # per animation: it also restores the panel's resting size afterwards.
        self._visualizer_closing = False
        self._visualizer_anim.finished.connect(self._on_visualizer_popup_finished)

        # Playlist panel.
        self._playlist_panel = _PlaylistPanel(self)
        self._playlist_panel.hide()
        self._playlist_panel.song_selected.connect(self._on_playlist_song_selected)
        self._playlist_anim = QPropertyAnimation(
            self._playlist_panel, b"geometry", self
        )
        self._playlist_anim.setDuration(320)
        self._playlist_anim.setEasingCurve(QEasingCurve.OutBack)
        self._playlist_closing = False
        self._playlist_anim.finished.connect(self._on_playlist_popup_finished)

        self._drag_target: str | None = None

        self._switching = False
        self._switch_ref_h = UI_REF_HEIGHT
        self._ui_switch_pix: QPixmap | None = None

    def get_lyrics_progress(self) -> float:
        return self._lyrics_progress

    def set_lyrics_progress(self, value: float) -> None:
        self._lyrics_progress = value
        self.update()

    lyricsProgress = Property(float, get_lyrics_progress, set_lyrics_progress)

    def get_vinyl_out_progress(self) -> float:
        return self._vinyl_out_progress

    def set_vinyl_out_progress(self, value: float) -> None:
        self._vinyl_out_progress = value
        self.update()

    vinylOutProgress = Property(
        float, get_vinyl_out_progress, set_vinyl_out_progress
    )

    def _set_vinyl_out(self, out: bool) -> None:
        """Animate the record to a given drawn-out state.

        Sliding out gets a small overshoot (OutBack) so it settles into place
        with a nudge; sliding back in is a plain decelerating toss.
        """
        if self._vinyl_dragging and not out:
            self._end_scratch()
        self._vinyl_out = bool(out)
        self._vinyl_out_anim.stop()
        self._vinyl_out_anim.setStartValue(self._vinyl_out_progress)
        self._vinyl_out_anim.setEndValue(1.0 if out else 0.0)
        self._vinyl_out_anim.setEasingCurve(
            QEasingCurve.OutBack if out else QEasingCurve.OutCubic
        )
        self._vinyl_out_anim.start()

    def _toggle_vinyl(self) -> None:
        """Slide the record in/out of its sleeve."""
        self._set_vinyl_out(not self._vinyl_out)

    def set_switching(self, active: bool) -> None:
        """Called by PageStack when a page-switch animation starts/ends.

        While switching the UI layer is frozen into a snapshot so the squeeze
        animation stays cheap; the checkerboard background keeps animating.
        """
        self._switching = active
        if active:
            self._switch_ref_h = max(1, self.height())
            self._ui_switch_pix = self._render_ui_snapshot(self.width())
        else:
            self._ui_switch_pix = None
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._page_visible = True
        self._timer.start()
        self._sync_rhythm_timer()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._page_visible = False
        self._timer.stop()
        self._sync_rhythm_timer()

    def _create_placeholder_cover(self) -> QPixmap:
        # Shared: identical for every page/track, so it is drawn once.
        cached = _get_placeholder_cover()
        if cached is not None:
            return cached
        size = 256
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0, QColor(118, 185, 0))
        gradient.setColorAt(1, QColor(70, 110, 0))
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, size, size, 24, 24)

        # Simple music note glyph.
        pen = QPen(QColor(255, 255, 255, 220))
        pen.setWidth(6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 255, 255, 220))
        note_x = size * 0.38
        stem_top = size * 0.30
        head_y = size * 0.68
        painter.drawEllipse(QPointF(note_x, head_y), 14, 10)
        painter.drawLine(int(note_x + 12), int(head_y - 4), int(note_x + 12), int(stem_top + 6))
        painter.drawEllipse(QPointF(note_x + 12, stem_top), 10, 8)
        painter.end()
        _store_placeholder_cover(pixmap)
        return pixmap

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def _setup_player(self) -> None:
        if not MULTIMEDIA_AVAILABLE:
            return
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(self._volume_slider.target)

        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.metaDataChanged.connect(self._on_metadata_changed)

        # PCM turntable engine for true scratch audio (reverse + pitch that
        # follows the hand). QMediaPlayer stays as the fallback backend and
        # for metadata/cover extraction.
        self._engine = None
        self._audio_backend = "qt"
        if MULTIMEDIA_AVAILABLE and VinylAudioEngine.supported():
            self._engine = VinylAudioEngine(self)
            self._engine.ready.connect(self._on_engine_ready)
            self._engine.failed.connect(self._on_engine_failed)
            self._engine.finished.connect(self._on_engine_finished)
            self._engine.set_volume(self._volume_slider.target)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._engine.shutdown)

    def _open_music_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "选择音乐目录", self._music_dir or ""
        )
        if not directory:
            return
        self.set_music_dir(directory, autoplay=True)
        # Tell the outside world: this page owns its own picker, so without
        # this the folder was never saved and the settings page kept showing
        # the previous one.
        self.music_dir_picked.emit(directory)

    def set_music_dir(self, directory: str, autoplay: bool = True) -> None:
        """Load a music folder (used by the picker and by the settings page)."""
        if not directory or not os.path.isdir(directory):
            return
        self._music_dir = directory
        files = []
        for name in sorted(os.listdir(directory), key=str.lower):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext in SUPPORTED_AUDIO_EXTS:
                files.append(path)
        if files:
            self._playlist = files
            self._playlist_index = 0
            self._load_track(files[0], auto_play=autoplay)
            self._playlist_panel.set_songs(self._playlist, self._playlist_index)
        else:
            self._playlist = []
            self._playlist_panel.set_songs([], -1)
        self.update()

    def clear_music_dir(self) -> None:
        """Forget the loaded folder and return the page to an empty state.

        Resets the displayed track too - cover, title, lyrics and the info
        panel - so nothing from the previous folder lingers on screen. Files
        on disk are never touched.
        """
        self._pause_playback()
        self._set_is_playing(False)
        self._music_dir = ""
        self._playlist = []
        self._playlist_index = -1
        self._current_track = None
        self._playlist_panel.set_songs([], -1)
        if self._engine is not None:
            self._engine.stop()
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())

        # Clear the on-screen track: placeholder sleeve, no lyrics, no info,
        # and the record slides back into its sleeve with the arm parked.
        had_lyrics = self._reset_track_state()
        self._update_lyrics_panel(had_lyrics, False)
        if self._vinyl_out:
            self._toggle_vinyl()
        self.update()

    def set_pcm_engine_enabled(self, enabled: bool) -> None:
        """Turn the PCM turntable engine on/off, reloading the current track.

        With it off the player uses QMediaPlayer, where backwards scratching is
        only approximated with slow forward playback plus seeks.
        """
        self._pcm_enabled = bool(enabled)
        if self._current_track:
            was_playing = self._is_playing
            self._load_track(self._current_track, auto_play=was_playing)

    def set_row_tooltips(self, enabled: bool) -> None:
        """Show/hide the hover label on the player's popup menu rows.

        Covers both panels: they share the same row list, which is why the
        settings page has one switch for the pair.
        """
        self._playlist_panel.set_row_tooltips(enabled)
        self._visualizer_panel.set_row_tooltips(enabled)

    # ------------------------------------------------------------------
    # Music popup menu
    # ------------------------------------------------------------------
    def _toggle_music_menu(self) -> None:
        """Toggle the music popup menu with a bouncy animation."""
        if self._music_menu.isVisible():
            self._hide_music_menu()
        else:
            self._show_music_menu()

    def _show_music_menu(self) -> None:
        """Popup the menu from the folder button with an OutBack scale effect."""
        btn = self._folder_btn_rect
        menu_w = self._music_menu.width()
        menu_h = self._music_menu.height()

        # Position above the button, aligned to the right edge.
        end_x = btn.right() - menu_w + 4
        end_y = btn.top() - menu_h - 8
        # Keep inside the widget bounds.
        end_x = max(8, min(end_x, self.width() - menu_w - 8))
        end_y = max(8, end_y)

        end_geo = QRect(end_x, end_y, menu_w, menu_h)
        # Start from a small rect anchored at the button center.
        start_geo = QRect(
            btn.center().x(),
            btn.center().y(),
            10,
            10,
        )

        self._music_menu.setGeometry(start_geo)
        self._music_menu.show()
        self._music_menu.raise_()

        self._menu_anim.stop()
        # Make sure any previous hide-on-finish is disconnected before the open
        # animation starts, otherwise the menu would hide right after opening.
        if self._menu_hide_connected:
            try:
                self._menu_anim.finished.disconnect(self._music_menu.hide)
                # Only connected while the animation runs; disconnecting an
                # unconnected signal raises and is not an error here.
            except Exception:
                pass
            self._menu_hide_connected = False
        self._menu_anim.setStartValue(start_geo)
        self._menu_anim.setEndValue(end_geo)
        self._menu_anim.setEasingCurve(QEasingCurve.OutBack)
        self._menu_anim.start()

    def _hide_music_menu(self) -> None:
        """Collapse the menu back toward the button."""
        if not self._music_menu.isVisible():
            return
        btn = self._folder_btn_rect
        start_geo = self._music_menu.geometry()
        end_geo = QRect(
            btn.center().x(),
            btn.center().y(),
            10,
            10,
        )

        self._menu_anim.stop()
        if self._menu_hide_connected:
            try:
                self._menu_anim.finished.disconnect(self._music_menu.hide)
                # As above.
            except Exception:
                pass
            self._menu_hide_connected = False
        self._menu_anim.finished.connect(self._music_menu.hide)
        self._menu_hide_connected = True
        self._menu_anim.setStartValue(start_geo)
        self._menu_anim.setEndValue(end_geo)
        self._menu_anim.setEasingCurve(QEasingCurve.InBack)
        self._menu_anim.start()

    def _on_music_menu_clicked(self, index: int) -> None:
        """Handle a click on a music menu item."""
        action = self._music_menu.item_data(index)

        if action == "set_folder":
            # Keep the menu open while the user picks a folder, then hide it.
            self._open_music_dir()
            self._hide_music_menu()
            return

        self._hide_music_menu()

        if action == "playlist":
            # The two panels pop out of the same button, so only one can be up:
            # opening either dismisses the other without an animation.
            self._hide_visualizer_panel(animate=False)
            self._toggle_playlist_panel()
        elif action == "visualizer":
            self._hide_playlist_panel(animate=False)
            self._toggle_visualizer_panel()
        elif action == "equalizer":
            # Placeholder: could open an equalizer panel.
            pass
        elif action == "play_mode":
            # Placeholder: cycle through loop/shuffle/single modes.
            pass
        elif action == "sleep_timer":
            # Placeholder: set a sleep timer.
            pass

    # ------------------------------------------------------------------
    # Background visualisation (可视化效果)
    # ------------------------------------------------------------------
    def visualizer(self) -> str:
        """Key of the visualisation currently painted."""
        return self._visualizer

    def set_visualizer(self, key: str, notify: bool = True) -> None:
        """Switch the background visualisation.

        An unknown key falls back to the default instead of leaving the page
        without a background. Each effect is an entry in `_VISUALIZER_ITEMS` plus
        a branch in `_draw_background`.

        `notify=False` is for restoring the saved choice at startup: it must not
        look like a user change, or the window would write the value straight
        back where it came from.
        """
        if key not in _VISUALIZER_KEYS:
            key = _VISUALIZER_DEFAULT
        if key == self._visualizer:
            return
        self._visualizer = key
        self.update()
        if notify:
            self.visualizer_changed.emit(key)

    def _toggle_visualizer_panel(self) -> None:
        if self._visualizer_panel.isVisible():
            self._hide_visualizer_panel()
        else:
            self._show_visualizer_panel()

    def _show_visualizer_panel(self) -> None:
        """Popup the effect panel, exactly the way the playlist panel pops up."""
        # Fill it first: the panel's height follows its list, and the geometry
        # below is computed from that height.
        labels = [title for title, _key in _VISUALIZER_ITEMS]
        current = _VISUALIZER_KEYS.index(self._visualizer)
        self._visualizer_panel.set_effects(labels, current)

        start_geo, end_geo = self._panel_popup_rects(self._visualizer_panel)
        # The dot the panel unfolds from is the start of the squeeze's progress.
        self._visualizer_panel.begin_popup_animation(start_geo.height())
        self._visualizer_panel.setGeometry(start_geo)
        self._visualizer_panel.show()
        self._visualizer_panel.raise_()

        self._visualizer_closing = False
        self._visualizer_anim.stop()
        self._visualizer_anim.setStartValue(start_geo)
        self._visualizer_anim.setEndValue(end_geo)
        self._visualizer_anim.setEasingCurve(QEasingCurve.OutBack)
        self._visualizer_anim.start()

    def _hide_visualizer_panel(self, animate: bool = True) -> None:
        """Collapse the effect panel back toward the folder button."""
        if not self._visualizer_panel.isVisible():
            return
        btn = self._folder_btn_rect
        start_geo = self._visualizer_panel.geometry()
        end_geo = QRect(btn.center().x(), btn.center().y(), 10, 10)

        self._visualizer_closing = True
        self._visualizer_anim.stop()
        if not animate:
            self._visualizer_panel.hide()
            self._visualizer_panel.end_popup_animation()
            return
        self._visualizer_panel.begin_popup_animation(end_geo.height())
        self._visualizer_anim.setStartValue(start_geo)
        self._visualizer_anim.setEndValue(end_geo)
        self._visualizer_anim.setEasingCurve(QEasingCurve.InBack)
        self._visualizer_anim.start()

    def _on_visualizer_popup_finished(self) -> None:
        """Animation over: finish a close off, and restore the resting size."""
        if self._visualizer_closing:
            self._visualizer_panel.hide()
        self._visualizer_panel.end_popup_animation()

    def _on_visualizer_effect_selected(self, index: int) -> None:
        """Apply the picked effect, then drop the panel."""
        if not 0 <= index < len(_VISUALIZER_ITEMS):
            self._hide_visualizer_panel()
            return
        # Apply first, so the background is already the new one as the panel
        # folds away over it.
        self.set_visualizer(_VISUALIZER_ITEMS[index][1])
        self._hide_visualizer_panel()

    def _toggle_playlist_panel(self) -> None:
        """Show/hide the playlist panel with a bouncy animation."""
        if self._playlist_panel.isVisible():
            self._hide_playlist_panel()
        else:
            self._show_playlist_panel()

    def _panel_popup_rects(self, panel: QWidget) -> tuple[QRect, QRect]:
        """Geometry for a popup panel: where it opens, and where it grows from.

        Shared by the playlist and the effect panels so both are presented in
        exactly the same way: above the folder button, right-aligned to it,
        unfolded out of a dot at the button's centre.
        """
        btn = self._folder_btn_rect
        panel_w = panel.width()
        panel_h = panel.height()

        # Position above the button, aligned to the right edge.
        end_x = btn.right() - panel_w + 4
        end_y = btn.top() - panel_h - 8
        end_x = max(8, min(end_x, self.width() - panel_w - 8))
        end_y = max(8, end_y)

        end_geo = QRect(end_x, end_y, panel_w, panel_h)
        start_geo = QRect(btn.center().x(), btn.center().y(), 10, 10)
        return start_geo, end_geo

    def _show_playlist_panel(self) -> None:
        """Popup the playlist panel beside the folder button."""
        start_geo, end_geo = self._panel_popup_rects(self._playlist_panel)

        self._playlist_panel.begin_popup_animation(start_geo.height())
        self._playlist_panel.setGeometry(start_geo)
        self._playlist_panel.set_songs(self._playlist, self._playlist_index)
        # Opening is when the playing song should be brought into view; picking a
        # song in the list must not move it (see _PlaylistItemList.set_songs).
        self._playlist_panel.scroll_to_current()
        self._playlist_panel.show()
        self._playlist_panel.raise_()

        self._playlist_closing = False
        self._playlist_anim.stop()
        self._playlist_anim.setStartValue(start_geo)
        self._playlist_anim.setEndValue(end_geo)
        self._playlist_anim.setEasingCurve(QEasingCurve.OutBack)
        self._playlist_anim.start()

    def _hide_playlist_panel(self, animate: bool = True) -> None:
        """Collapse the playlist panel back toward the button."""
        if not self._playlist_panel.isVisible():
            return
        btn = self._folder_btn_rect
        start_geo = self._playlist_panel.geometry()
        end_geo = QRect(
            btn.center().x(),
            btn.center().y(),
            10,
            10,
        )

        self._playlist_closing = True
        self._playlist_anim.stop()
        if not animate:
            # Used to dismiss it in favour of the other panel, which opens in
            # the same spot: a collapse animation there would just be in the way.
            self._playlist_panel.hide()
            self._playlist_panel.end_popup_animation()
            return
        self._playlist_panel.begin_popup_animation(end_geo.height())
        self._playlist_anim.setStartValue(start_geo)
        self._playlist_anim.setEndValue(end_geo)
        self._playlist_anim.setEasingCurve(QEasingCurve.InBack)
        self._playlist_anim.start()

    def _on_playlist_popup_finished(self) -> None:
        """Animation over: finish a close off, and restore the resting size."""
        if self._playlist_closing:
            self._playlist_panel.hide()
        self._playlist_panel.end_popup_animation()

    def _on_playlist_song_selected(self, index: int) -> None:
        """Play the song selected from the playlist panel."""
        if not self._playlist or index < 0 or index >= len(self._playlist):
            return
        self._playlist_index = index
        self._load_track(self._playlist[index], auto_play=True)
        self._playlist_panel.set_songs(self._playlist, self._playlist_index)

    def _reset_track_state(self, next_path: str | None = None) -> bool:
        """Clear everything describing the track on screen.

        Returns whether lyrics were displayed before, so the caller can decide
        how to animate the lyrics panel. The panel itself is not touched here:
        a track change keeps it in place while simply clearing the folder
        should slide it away.

        *next_path* is the track about to be loaded. When it is the same file that is already
        displayed, the cover and its palette are kept: reloading a track must not blank the
        artwork, and Qt will not hand it back. Measured on the real widget -- a plain
        `setSource(url)` for the URL already playing emits `metaDataChanged` **zero** times,
        while a first load emits it once. So clearing the cover here and waiting for the signal
        to restore it works once and then leaves the placeholder (or, on files whose metadata
        offers only `ThumbnailImage`, silently drops from full size to the 256 px thumbnail).
        """
        had_lyrics = self._has_lyrics()
        reloading_same = next_path is not None and next_path == self._current_track
        self._song_title = ""
        self._song_artist = ""
        self._album = ""
        self._lyrics = []
        # The hover points into the lyric list, which is being replaced: an index from the
        # previous song would name a different line here.
        self._lyrics_hover_index = -1
        self._lyric_height_cache.clear()
        self._track_info = {}
        self._info_scroll = {}
        if not reloading_same:
            self._cover = self._create_placeholder_cover()
            self._cover_path = None
        self._source_label = ""
        self._container_cover = None
        self._duration = 0
        self._progress_slider.set_target(0.0)
        self._update_vinyl_label_color()
        if not reloading_same:
            self._apply_music_palette(
                ColorExtractor.extract_palette(self._cover, count=5)
            )

        # Reset lyrics scrolling state.
        self._lyrics_scroll_offset = 0.0
        self._lyrics_scroll_target = 0.0
        self._lyrics_scroll_velocity = 0.0
        self._lyrics_active_seen = -1
        self._lyrics_anim_from = -1
        self._lyrics_anim_to = -1
        self._lyrics_anim_elapsed = 0.0
        self._lyrics_line_springs.clear()
        self._lyrics_auto_follow = True
        self._lyrics_resume_timer.stop()
        self._lyrics_dragging = False
        self._lyrics_drag_moved = False

        # Reset the turntable for a fresh record.
        self._vinyl_scratch_delta = 0.0
        self._vinyl_angular_velocity = 0.0
        self._vinyl_display_velocity = 0.0
        self._angle_offset_ms = 0.0
        return had_lyrics

    def _load_track(self, path: str, auto_play: bool = False) -> None:
        old_has_lyrics = self._reset_track_state(path)
        self._current_track = path
        self._song_title = os.path.splitext(os.path.basename(path))[0]
        self._song_artist = "未知艺术家"

        # An .ncm is a wrapper, not a stream: unpack it first and work with the
        # plain audio file from here on. The playlist keeps the original path
        # so the file list still shows what the user actually has on disk.
        play_path = path
        ncm_track = decode_ncm(path) if path.lower().endswith(".ncm") else None
        if ncm_track is not None:
            if not ncm_track.path:
                # The wrapper still yielded real tags, so show the track and the
                # reason rather than a bare filename.
                self._set_decode_error(ncm_track)
                return
            play_path = ncm_track.path
            self._source_label = MUSIC_SOURCE_NCM
            if ncm_track.title:
                self._song_title = ncm_track.title
            if ncm_track.artist:
                self._song_artist = ncm_track.artist
            if ncm_track.album:
                self._album = ncm_track.album
            if ncm_track.duration_ms:
                self._duration = ncm_track.duration_ms
            # The unpacked stream carries no cover art and QMediaPlayer reports
            # none, so keep the container's own image and re-apply it whenever
            # metadata changes arrive (see _on_metadata_changed).
            cover = cover_pixmap(ncm_track.cover_data)
            if cover is not None:
                self._container_cover = cover
                self._cover = cover
                self._cover_path = path

        self._load_lyrics(play_path)
        self._load_track_info(play_path)

        # Prime the duration from ffprobe so the UI works before the PCM
        # engine finishes decoding; the engine's exact value overrides it.
        dur_sec = self._track_info.get("duration_sec")
        if dur_sec:
            self._duration = int(dur_sec * 1000)
        elif ncm_track is not None and ncm_track.duration_ms:
            # The container states the duration even when ffprobe is slow.
            self._duration = ncm_track.duration_ms

        # Prefer the PCM turntable engine; fall back to QMediaPlayer.
        #
        # The engine has to be stopped explicitly when it is not the chosen backend. `open()`
        # stops the previous stream itself, but turning PCM off in the settings skips `open()`
        # entirely -- so the engine kept playing whatever it had, and the QMediaPlayer then
        # started on top of it, which put two audio streams out at once. The same applies when
        # `open()` fails and the player takes over.
        self._audio_backend = "qt"
        if not (
            self._pcm_enabled
            and self._engine is not None
            and self._engine.open(play_path)
        ):
            if self._engine is not None:
                self._engine.stop()
        else:
            self._audio_backend = "pcm"

        self._update_lyrics_panel(old_has_lyrics, self._has_lyrics())

        # Keep the playlist panel in sync with the current track.
        self._playlist_panel.set_songs(self._playlist, self._playlist_index)

        # QMediaPlayer still gets the source: it feeds metadata and cover art
        # in PCM mode, and is the actual playback backend in Qt mode.
        if self._player is not None:
            self._player.setSource(QUrl.fromLocalFile(play_path))
        if auto_play:
            self._start_playback()
        elif self._player is not None:
            self._player.pause()
        self.update()

    def _set_decode_error(self, track) -> None:
        """Show a track that could not be opened, instead of playing noise.

        The wrapper still yields real tags even when its audio layer cannot be
        unpacked, so the record keeps its title and artist; the reason goes in
        the info panel's tech line, which scrolls when it is too long.
        """
        self._audio_backend = "qt"
        if track.title:
            self._song_title = track.title
            self._song_artist = track.artist or "未知艺术家"
            if track.album:
                self._album = track.album
        else:
            self._song_title = os.path.splitext(os.path.basename(
                self._current_track or ""))[0] or "无法播放"
            self._song_artist = "未知艺术家"
        self._track_info["format"] = track.error or "无法解码 ncm"
        self._duration = 0
        self._progress_slider.set_target(0.0)
        self._playlist_panel.set_songs(self._playlist, self._playlist_index)
        self.update()

    def _update_lyrics_panel(self, old_has: bool, new_has: bool) -> None:
        """Animate the lyrics panel in/out when its presence changes."""
        if old_has == new_has:
            self._lyrics_progress = 1.0 if new_has else 0.0
            return
        start = 1.0 if old_has else 0.0
        end = 1.0 if new_has else 0.0
        self._lyrics_anim.stop()
        self._lyrics_anim.setStartValue(start)
        self._lyrics_anim.setEndValue(end)
        # Pop in with a slight overshoot; slide out smoothly.
        curve = QEasingCurve.OutBack if new_has else QEasingCurve.InOutCubic
        self._lyrics_anim.setEasingCurve(curve)
        self._lyrics_anim.start()

    def _resume_lyrics_auto_follow(self) -> None:
        """Re-enable auto-scroll after the user finishes a manual drag."""
        self._lyrics_auto_follow = True

    def _load_lyrics(self, path: str) -> None:
        """Load embedded or sidecar lyrics for the given track."""
        raw = self._find_lyrics_file(path)
        if not raw:
            ext = os.path.splitext(path)[1].lower()
            if MUTAGEN_AVAILABLE:
                raw = self._read_lyrics_with_mutagen(path, ext)
            if not raw:
                raw = self._read_lyrics_with_ffprobe(path)
            if not raw and ext == ".flac":
                raw = self._read_flac_lyrics(path)
        if not raw:
            return
        self._lyrics = self._parse_lrc(raw)
        self._lyric_height_cache.clear()

    def _find_lyrics_file(self, path: str) -> str:
        """Look for a .lrc/.txt file next to the audio file."""
        base = os.path.splitext(path)[0]
        for ext in (".lrc", ".txt"):
            try:
                lrc_path = base + ext
                if os.path.isfile(lrc_path):
                    with open(lrc_path, "r", encoding="utf-8") as f:
                        return f.read()
                # A sidecar .lrc that exists but cannot be read (encoding,
                # permissions) means no lyrics from that source.
            except Exception:
                pass
        return ""

    def _read_lyrics_with_mutagen(self, path: str, ext: str) -> str:
        try:
            if ext == ".mp3":
                audio = MP3(path)
                if audio.tags:
                    for key in audio.tags:
                        if key.startswith("USLT"):
                            return str(audio.tags[key])
            elif ext in (".flac", ".ogg"):
                audio = FLAC(path)
                for key in ("LYRICS", "UNSYNCEDLYRICS"):
                    if key in audio:
                        value = audio[key]
                        if isinstance(value, list):
                            value = value[0]
                        return str(value)
            elif ext == ".m4a":
                audio = MP4(path)
                for key in ("©lyr", "----:com.apple.iTunes:LYRICS"):
                    if key in audio:
                        value = audio[key]
                        if isinstance(value, list):
                            value = value[0]
                        return str(value)
            # mutagen is optional: an import failure or a file it cannot
            # parse means no embedded lyrics, and ffprobe is tried next.
        except Exception:
            pass
        return ""

    def _read_lyrics_with_ffprobe(self, path: str) -> str:
        """Use ffprobe to read any 'lyrics-*' / 'LYRICS' tag from the file."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                # Without this each ffprobe opens its own console window.
                **no_window_kwargs(),
            )
            if result.returncode != 0 or not result.stdout:
                return ""
            info = json.loads(result.stdout)
            tags = info.get("format", {}).get("tags", {})
            candidates = []
            for key, value in tags.items():
                upper = key.upper()
                if upper == "LYRICS":
                    return str(value)
                if "LYRICS" in upper:
                    candidates.append((key, str(value)))
            # Prefer the shortest key (e.g. lyrics-eng over lyrics-XXX-unknown).
            if candidates:
                candidates.sort(key=lambda item: len(item[0]))
                return candidates[0][1]
            # No ffprobe, a timeout, or output that is not JSON all
            # mean this source has no lyrics.
        except Exception:
            pass
        return ""

    def _read_flac_lyrics(self, path: str) -> str:
        """Parse a FLAC Vorbis comment block looking for LYRICS."""
        try:
            with open(path, "rb") as f:
                if f.read(4) != b"fLaC":
                    return ""
                while True:
                    header = f.read(4)
                    if len(header) != 4:
                        break
                    last_block = bool(header[0] & 0x80)
                    block_type = header[0] & 0x7F
                    block_len = int.from_bytes(header[1:4], "big")
                    data = f.read(block_len)
                    if len(data) != block_len:
                        break
                    if block_type == 4:  # VORBIS_COMMENT
                        return self._parse_vorbis_comment(data, "LYRICS")
                    if last_block:
                        break
            # A malformed FLAC comment block is treated as
            # having no lyrics rather than crashing the load.
        except Exception:
            pass
        return ""

    def _parse_vorbis_comment(self, data: bytes, field: str) -> str:
        idx = 0
        vendor_len = int.from_bytes(data[idx : idx + 4], "little")
        idx += 4 + vendor_len
        if idx + 4 > len(data):
            return ""
        comment_count = int.from_bytes(data[idx : idx + 4], "little")
        idx += 4
        field_up = field.upper()
        for _ in range(comment_count):
            if idx + 4 > len(data):
                break
            comment_len = int.from_bytes(data[idx : idx + 4], "little")
            idx += 4
            if idx + comment_len > len(data):
                break
            comment = self._decode_vorbis_text(data[idx : idx + comment_len])
            idx += comment_len
            if "=" in comment:
                key, value = comment.split("=", 1)
                if key.upper() == field_up:
                    return value
        return ""

    def _decode_vorbis_text(self, data: bytes) -> str:
        """Decode a Vorbis comment string, tolerating common legacy encodings."""
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    def _parse_lrc(self, raw: str) -> list[tuple[float, str]]:
        """Parse LRC timestamps; lines without timestamps are kept as plain text."""
        lines: list[tuple[float, str]] = []
        timed = False
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            tags = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", line)
            text = re.sub(r"\[\d+:\d+(?:\.\d+)?\]", "", line).strip()
            if not text:
                continue
            if tags:
                timed = True
                for minutes, seconds in tags:
                    try:
                        t = int(minutes) * 60 + float(seconds)
                        lines.append((t, text))
                        # One unparseable timestamp skips that line and keeps the rest
                        # of the lyrics.
                    except ValueError:
                        pass
            else:
                lines.append((-1.0, text))
        if timed:
            lines.sort(key=lambda item: item[0])
            deduped: list[tuple[float, str]] = []
            seen: set[tuple[float, str]] = set()
            for t, text in lines:
                key = (round(t, 2), text)
                if key not in seen:
                    seen.add(key)
                    deduped.append((t, text))
            lines = deduped
        return lines

    def _load_track_info(self, path: str) -> None:
        """Read technical metadata (format, bitrate, sample rate, cover size, album)."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    path,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                # This one runs on every track change; without it the console flashes.
                **no_window_kwargs(),
            )
            if result.returncode != 0 or not result.stdout:
                return
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            fmt_name = fmt.get("format_name", "").split(",")[0].strip().upper()
            if fmt_name:
                self._track_info["format"] = fmt_name
            br = fmt.get("bit_rate")
            if br:
                self._track_info["bitrate"] = int(br)
            dur = fmt.get("duration")
            if dur:
                self._track_info["duration_sec"] = float(dur)

            tags = fmt.get("tags", {})
            album = tags.get("ALBUM") or tags.get("Album")
            if album and not self._album:
                self._album = _meta_text(album)

            for stream in data.get("streams", []):
                if stream.get("codec_type") == "audio":
                    sr = stream.get("sample_rate")
                    if sr:
                        self._track_info["sample_rate"] = int(sr)
                    ch = stream.get("channels")
                    if ch is not None:
                        self._track_info["channels"] = int(ch)
                    bps = stream.get("bits_per_raw_sample") or stream.get(
                        "bits_per_sample"
                    )
                    if bps:
                        self._track_info["bits_per_sample"] = int(bps)
                elif stream.get("codec_type") == "video":
                    disp = stream.get("disposition", {})
                    if disp.get("attached_pic") == 1:
                        w = stream.get("width")
                        h = stream.get("height")
                        if w and h:
                            self._track_info["cover_width"] = int(w)
                            self._track_info["cover_height"] = int(h)
        except Exception:
            # Track details are decoration: if ffprobe is missing, times out, or returns
            # something unexpected, the info panel simply shows less. Nothing here is
            # required for playback.
            pass

    def _format_time(self, ms: int) -> str:
        total = max(0, int(ms / 1000))
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _current_lyric_index(self) -> int:
        if not self._lyrics or not self._current_track:
            return -1
        if not any(t >= 0 for t, _ in self._lyrics):
            return -1
        pos = self._playback_position() / 1000.0
        idx = -1
        for i, (t, _) in enumerate(self._lyrics):
            if t <= pos:
                idx = i
            else:
                break
        return idx

    def _lyrics_size_spec(self) -> tuple[int, int, int]:
        """The selected tier as (idle font size, active font size, edge margin)."""
        index = max(0, min(len(LYRICS_SIZES) - 1, int(self._lyrics_size)))
        return LYRICS_SIZES[index][1]

    def set_lyrics_fade(self, enabled: bool, notify: bool = False) -> None:
        """Fade the non-active lyric lines under the colour visualiser.

        `notify` exists for the same reason as the other setters': restoring the saved value at
        startup must not look like a user change.
        """
        enabled = bool(enabled)
        if enabled == self._lyrics_fade:
            return
        self._lyrics_fade = enabled
        self.update()
        if notify:
            self.lyrics_fade_changed.emit(enabled)

    def lyrics_size(self) -> int:
        """Index into `LYRICS_SIZES` of the current lyric size."""
        return self._lyrics_size

    def set_lyrics_size(self, index: int, notify: bool = False) -> None:
        """Set how large the lyric lines are: 0 small, 1 medium, 2 large.

        Heights are cached per alignment and width, so the cache is dropped when the size changes.
        `notify` exists for the same reason as `set_lyrics_align`'s: restoring the saved value at
        startup must not look like a user change.
        """
        index = max(0, min(len(LYRICS_SIZES) - 1, int(index)))
        if index == self._lyrics_size:
            return
        self._lyrics_size = index
        self._lyric_height_cache.clear()
        self.update()
        if notify:
            self.lyrics_size_changed.emit(index)

    def _lyrics_align_flag(self) -> Qt.AlignmentFlag:
        """Qt alignment flag for the saved lyric position (left / centre / right)."""
        return (Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight)[
            max(0, min(2, self._lyrics_align))
        ]

    def lyrics_align(self) -> int:
        """Index into `LYRICS_ALIGNMENTS` of the current lyric alignment."""
        return self._lyrics_align

    def set_lyrics_align(self, index: int, notify: bool = False) -> None:
        """Set where the lyric lines sit: 0 left, 1 centre (default), 2 right.

        Heights are cached per alignment, so the cache is dropped when it changes;
        `notify` exists for the same reason as `set_visualizer`'s -- restoring the
        saved value at startup must not look like a user change.
        """
        index = max(0, min(len(LYRICS_ALIGNMENTS) - 1, int(index)))
        if index == self._lyrics_align:
            return
        self._lyrics_align = index
        self._lyric_height_cache.clear()
        self.update()
        if notify:
            self.lyrics_align_changed.emit(index)

    def _lyric_drawn_height(self, target: QPainter, i: int, line: str, max_w: int,
                            text_flags) -> int:
        """How tall *line* will be when it is drawn, font and all.
    
        Used by the layout walk and by the pass that draws a line sharp afterwards, so both
        agree on the box. Measuring with a different font than the one that paints is what
        made the active line come out small: its box was sized for the tier's idle font while
        the text was drawn with the larger animated one and had to fit inside it.
        """
        font = ui_font(int(round(self._lyrics_line_font_size(i, i == self._current_lyric_index()))))
        font.setWeight(QFont.Bold)
        target.setFont(font)
        return target.fontMetrics().boundingRect(QRect(0, 0, max_w, 0), text_flags, line).height()

    def _lyric_entry_width(self, i: int, max_w: int) -> int:
        """Return the width the wrapped text of a lyric entry actually occupies.

        Measured with the same font, alignment flag and wrapping as the height, so the two agree about
        where the words are. Used for the hover region's left and right edges: a short line should not
        count as reaching the full column.

        Memoised on the same terms as the height, and measured for every line rather than only the
        drawn ones -- a line left out of the blurred layer is never measured while drawing, and the
        region would then be narrower than the words on the frames just after the release.
        """
        if max_w != self._lyric_height_width:
            self._lyric_height_width = max_w
            self._lyric_height_cache.clear()
        align = self._lyrics_align_flag()
        idle_size, _active_size, _margin = self._lyrics_size_spec()
        font = ui_font(idle_size)
        font.setWeight(QFont.Bold)
        br = QFontMetrics(font).boundingRect(
            QRect(0, 0, max_w, 0),
            Qt.TextWordWrap | align,
            self._lyrics[i][1],
        )
        return br.width()

    def _lyric_entry_height(self, i: int, max_w: int) -> int:
        """Return the wrapped height of a single lyric entry, memoised.

        Measured with the SAME alignment flag the line is drawn with: Qt wraps differently per
        flag, and a height that disagrees with the drawing would make the lines drift apart
        from the scroll offsets. Also measured with the same font -- the selected tier's idle
        size -- for the same reason.
        """
        if max_w != self._lyric_height_width:
            self._lyric_height_width = max_w
            self._lyric_height_cache.clear()
        align = self._lyrics_align_flag()
        idle_size, _active_size, _margin = self._lyrics_size_spec()
        key = (i, max_w, idle_size, int(align))
        cached = self._lyric_height_cache.get(key)
        if cached is not None:
            return cached

        _, line = self._lyrics[i]
        # The tier's idle size, for every line. The drawing code uses the animated size for the
        # active line alone, so measuring the lines above it at the active size -- which is what
        # this did, hard-coded at 17/19 regardless of tier -- put the scroll target several lines
        # away from where the text actually landed once the tier grew.
        font = ui_font(idle_size)
        font.setWeight(QFont.Bold)
        fm = QFontMetrics(font)
        br = fm.boundingRect(
            QRect(0, 0, max_w, 0),
            Qt.TextWordWrap | align,
            line,
        )
        self._lyric_height_cache[key] = br.height()
        return br.height()

    def _lyrics_content_height(self, max_w: int) -> float:
        """Total scrolled height of all lyric entries with gaps."""
        total = 0.0
        for i in range(len(self._lyrics)):
            total += self._lyric_entry_height(i, max_w)
            if i < len(self._lyrics) - 1:
                total += LYRICS_ENTRY_GAP
        return total

    def _lyrics_scroll_target_for_active(self, active: int, max_w: int) -> float:
        """Scroll offset that keeps the active entry near the second visible row."""
        if active < 0 or not self._lyrics:
            return 0.0

        _idle, _active, margin = self._lyrics_size_spec()
        panel_h = self.height()
        avail_h = max(1, panel_h - 2 * margin)
        # Pin the active line about a third of the way down the visible band, one row above where
        # it used to sit. Both the margin and the line heights come from the selected size tier, so
        # this stays one row up at every size instead of only at the size it was measured at.
        desired_active_top = margin + avail_h * 0.21

        active_offset = 0.0
        for i in range(active):
            active_offset += (
                self._lyric_entry_height(i, max_w) + LYRICS_ENTRY_GAP
            )

        base_y = 50  # must match _draw_lyrics
        return base_y + active_offset - desired_active_top

    def _lyrics_scroll_offset_range(
        self, max_w: int, active: int
    ) -> tuple[float, float]:
        """Allowed scroll range: keep lyrics reachable without large blank areas."""
        n = len(self._lyrics)
        if n == 0:
            return (0.0, 0.0)

        _idle, _active, margin = self._lyrics_size_spec()
        panel_h = self.height()
        visible_top = margin
        visible_bottom = panel_h - margin
        base_y = 50
        has_timing = any(t >= 0 for t, _ in self._lyrics)

        if has_timing:
            first_offset = self._lyrics_scroll_target_for_active(0, max_w)
            last_offset = self._lyrics_scroll_target_for_active(n - 1, max_w)
        else:
            first_offset = last_offset = 0.0

        total_h = self._lyrics_content_height(max_w)
        first_h = self._lyric_entry_height(0, max_w)
        last_h = self._lyric_entry_height(n - 1, max_w)

        # Top-aligned: first line sits at the top edge.
        top_aligned = base_y - visible_top
        # Bottom-aligned: last line sits at the bottom edge.
        bottom_aligned = base_y + total_h - visible_bottom

        # When everything fits, prefer a centred view.
        if total_h <= visible_bottom - visible_top:
            center_offset = base_y - (panel_h - total_h) / 2
        else:
            center_offset = (top_aligned + bottom_aligned) / 2

        candidates = [top_aligned, bottom_aligned, center_offset]
        if has_timing:
            candidates.extend([first_offset, last_offset])

        min_offset = min(candidates)
        max_offset = max(candidates)
        return (min_offset, max_offset)

    def _clamp_lyrics_scroll_offset(self, max_w: int | None = None) -> None:
        """Keep the scroll offset inside the content bounds."""
        if not self._lyrics:
            self._lyrics_scroll_offset = 0.0
            return
        has_timing = any(t >= 0 for t, _ in self._lyrics)
        active = self._current_lyric_index() if has_timing else -1
        if max_w is None:
            panel_w = int(self.width() * 0.5 * self._lyrics_progress)
            max_w = max(20, panel_w - 60)
        if max_w <= 0:
            return

        min_offset, max_offset = self._lyrics_scroll_offset_range(max_w, active)
        self._lyrics_scroll_offset = max(
            min_offset, min(self._lyrics_scroll_offset, max_offset)
        )

    def _update_lyrics_scroll(self) -> None:
        """Auto-follow the active lyric or keep a manual scroll in bounds."""
        if not self._lyrics or self._lyrics_dragging:
            return
        panel_w = int(self.width() * 0.5 * self._lyrics_progress)
        max_w = max(20, panel_w - 60)
        if max_w <= 0:
            return

        has_timing = any(t >= 0 for t, _ in self._lyrics)
        active = self._current_lyric_index() if has_timing else -1

        # A change of active line is what sets the motion off. Detected here because this is
        # the one place that already tracks which line is current.
        if active != self._lyrics_active_seen:
            self._start_lyrics_line_anim(self._lyrics_active_seen, active)
            self._lyrics_active_seen = active

        if self._lyrics_auto_follow and has_timing and active >= 0:
            target = self._lyrics_scroll_target_for_active(active, max_w)
            # Spring rather than ease: the offset is integrated in
            # _update_lyrics_line_springs, so it can pass the target and come back. The old
            # form -- offset += (target - offset) * 0.12 -- could only ever approach.
            self._lyrics_scroll_target = target
        else:
            self._lyrics_scroll_target = self._lyrics_scroll_offset

        self._clamp_lyrics_scroll_offset(max_w)

    def _advance_spring(
        self, value: float, velocity: float, target: float, omega: float,
        damping_ratio: float, dt_ms: float,
    ) -> tuple[float, float]:
        """One step of a damped spring, in milliseconds.

        *omega* is the undamped natural frequency in radians per second and *damping_ratio* the
        fraction of critical damping: 1.0 arrives as fast as possible without overshooting,
        below 1.0 overshoots, above 1.0 is sluggish. Both are physical quantities, so the same
        pair gives the same motion at any frame rate.

        Two earlier attempts were wrong in instructive ways. The first scaled velocity by
        `damping ** dt` with damping as a per-millisecond retention, which was not tunable at
        all: 0.62 destroyed 99.95% of the velocity every frame (no overshoot, the offset simply
        collapsed onto the target) while 0.90 diverged. The second scaled the damping to the
        spring but kept the constants of the frame-based recursive form used elsewhere in this
        file (`v += (target - value) * k; v *= d`) -- those k values are per-frame, not per
        second, and feeding them to an integrator working in seconds made every combination
        diverge to thousands of pixels.
        """
        remaining = dt_ms
        while remaining > 0.0:
            # Sub-stepped so a long frame behaves like several short ones: the integrator is
            # explicit and goes unstable once omega * dt grows large.
            span = min(8.0, remaining)
            remaining -= span
            step = span / 1000.0
            velocity += (-(omega * omega) * (value - target)
                         - 2.0 * damping_ratio * omega * velocity) * step
            value += velocity * step
        return value, velocity

    def _update_lyrics_fade(self, dt_ms: float) -> None:
        """Move the panel's fade towards its target, and repaint while it is moving.

        Separate from the line springs because it is one value for the whole panel rather than a state
        per line, but advanced by the same function so it settles the same way.
        """
        self._refresh_lyrics_fade()
        # 1 at rest (fully faded), 0 while the pointer is releasing the effect.
        target = 0.0 if self._lyrics_fade_lifted else 1.0
        if (abs(self._lyrics_fade_value - target) < LYRICS_FADE_SETTLE
                and abs(self._lyrics_fade_velocity) < LYRICS_FADE_SETTLE):
            if self._lyrics_fade_value != target:
                self._lyrics_fade_value = target
                self._lyrics_fade_velocity = 0.0
                self.update()
            return
        self._lyrics_fade_value, self._lyrics_fade_velocity = self._advance_spring(
            self._lyrics_fade_value, self._lyrics_fade_velocity, target,
            LYRICS_FADE_SPRING_OMEGA, LYRICS_FADE_SPRING_RATIO, dt_ms,
        )
        # The fade is applied while drawing the lines, so the painting has to happen again for the
        # movement to be visible at all.
        self.update()

    def _update_lyrics_line_springs(self, dt_ms: float) -> None:
        """Advance the list's scroll spring and every line still rippling."""
        if self._lyrics_dragging:
            # A drag owns the offset; let the springs die rather than fight the pointer.
            self._lyrics_scroll_velocity = 0.0
            self._lyrics_line_springs.clear()
            return

        # The wave's clock is the same accumulated frame time the springs integrate against,
        # not wall time. Mixing the two is what made an earlier attempt look broken: with the
        # real clock, a line whose delay had not elapsed simply never moved, and any caller
        # driving frames faster than real time saw the ripple stand still.
        self._lyrics_anim_elapsed += dt_ms

        self._lyrics_scroll_offset, self._lyrics_scroll_velocity = self._advance_spring(
            self._lyrics_scroll_offset, self._lyrics_scroll_velocity,
            self._lyrics_scroll_target,
            LYRICS_SCROLL_SPRING_OMEGA, LYRICS_SCROLL_SPRING_RATIO, dt_ms,
        )

        if not self._lyrics_line_springs:
            return

        elapsed = self._lyrics_anim_elapsed
        for index in list(self._lyrics_line_springs):
            if elapsed < self._lyrics_wave_delay(index):
                # This line has not joined in yet; the wave reaches it later.
                continue
            offset, velocity = self._lyrics_line_springs[index]
            # The line that just became current bounces; the ones that merely travel with the
            # ripple do not. Two springs, chosen from their measured overshoot.
            if index == self._lyrics_anim_to:
                omega, ratio = LYRICS_LINE_SPRING_OMEGA, LYRICS_LINE_SPRING_RATIO
                settle_px, settle_v = LYRICS_BOUNCE_SETTLE_PX, None
            else:
                omega, ratio = LYRICS_RIPPLE_SPRING_OMEGA, LYRICS_RIPPLE_SPRING_RATIO
                settle_px, settle_v = LYRICS_SPRING_SETTLE_PX, LYRICS_SPRING_SETTLE_V
            offset, velocity = self._advance_spring(
                offset, velocity, 0.0, omega, ratio, dt_ms,
            )
            if settle_v is None:
                settled = abs(offset) < settle_px
            else:
                settled = abs(offset) < settle_px and abs(velocity) < settle_v
            if settled:
                # Dropped here, and _lyrics_line_offset reports exactly 0 for a line with no
                # entry -- so the line lands on its resting place instead of the fraction of a
                # pixel it happened to stop at. With the spring's overshoot larger than the
                # settle threshold, that remainder was otherwise permanent.
                del self._lyrics_line_springs[index]
            else:
                self._lyrics_line_springs[index] = [offset, velocity]

    def _lyrics_wave_delay(self, index: int) -> float:
        """Stagger for one line, in ms: grows with distance from the line that changed."""
        origin = self._lyrics_anim_to if self._lyrics_anim_to >= 0 else self._lyrics_anim_from
        if origin < 0:
            return 0.0
        return min(abs(index - origin), LYRICS_WAVE_SPAN) * LYRICS_WAVE_STAGGER_MS

    def _lyrics_line_offset(self, index: int) -> float:
        """Current ripple offset of one line, or 0 when it is at rest.

        A line with no spring entry reports exactly 0, so the settle step lands it on its resting
        place rather than on the fraction of a pixel it stopped at.

        This deliberately does NOT zero small offsets by itself. An earlier version reported 0 for
        anything under the settle threshold, and that silently ate the arriving line's overshoot:
        with the bounce spring the overshoot around the crossing is only a few tenths of a pixel,
        so the reading looked perfectly clean while the bounce was gone. What counts as settled
        belongs to the spring that owns the value, not to this getter.
        """
        entry = self._lyrics_line_springs.get(index)
        return 0.0 if entry is None else entry[0]

    def _lyrics_arrival_alpha(self, index: int) -> float:
        """Opacity multiplier for the line that just arrived, 0..1.

        Rises to fully opaque as the line comes up, driven by the same displacement the font size
        uses, so it needs no clock of its own. This is the arrival's signature: the line being
        left slides a full row along with everything else, which reads as motion but not as an
        event, while a line appearing where nothing was reads as the event.
        """
        if LYRICS_ARRIVAL_FADE <= 0.0 or LYRICS_LINE_LIFT_PX <= 0.0:
            return 1.0
        if index != self._lyrics_anim_to:
            return 1.0
        offset = self._lyrics_line_offset(index)
        # offset runs LIFT -> 0 -> slightly past 0, so the first part is the arrival.
        mix = 1.0 - max(0.0, min(1.0, offset / LYRICS_LINE_LIFT_PX))
        return max(0.0, min(1.0, mix / LYRICS_ARRIVAL_FADE))

    def _lyrics_line_font_size(self, index: int, is_active: bool) -> float:
        """Font size for one line, animated between the idle and active sizes.
        The active line used to switch between 17 and 19 with no transition, which is a visible
        jolt at the moment the line changes. The line's own displacement doubles as the blend
        here: the two sizes are the ends of its travel, so it grows on the way up and shrinks on
        the way back with no separate progress value to keep.
        """
        idle_size, active_size, _margin = self._lyrics_size_spec()
        if LYRICS_LINE_LIFT_PX <= 0.0:
            return active_size if is_active else idle_size
        offset = self._lyrics_line_offset(index)
        if is_active and self._lyrics_anim_to == index:
            # offset runs LIFT -> 0 -> (overshoot below 0), so this runs 0 -> 1 -> past 1.
            mix = 1.0 - max(-0.5, min(1.0, offset / LYRICS_LINE_LIFT_PX))
        elif not is_active and self._lyrics_anim_from == index and LYRICS_LINE_PUSH_PX > 0.0:
            mix = 1.0 - max(0.0, min(1.0, -offset / LYRICS_LINE_PUSH_PX))
        else:
            mix = 0.0
        return (active_size * mix
                + idle_size * (1.0 - mix))

    def _start_lyrics_line_anim(self, previous: int, current: int) -> None:
        """Arm the motion a line change sets off.

        Two things move, deliberately kept apart: the list's scroll spring carries the new line
        to its resting place, and the ripple is a per-line displacement that decays back to
        zero -- down the list, one line after another, so the change travels instead of arriving
        everywhere at once.
        """
        self._lyrics_anim_from = previous
        self._lyrics_anim_to = current
        self._lyrics_anim_elapsed = 0.0
        self._lyrics_line_springs.clear()
        if current < 0:
            return
        # The ripple goes down first, then the two lines that have motion of their own
        # overwrite it. The order matters: the outgoing line sits one line away from the
        # incoming one, so it falls inside the ripple's range and would otherwise have its push
        # replaced by the generic displacement and never move.
        if LYRICS_WAVE_STAGGER_MS > 0.0:
            for index in range(len(self._lyrics)):
                if index == current or index == previous:
                    # These two have motion of their own; the ripple is for the rest of the
                    # panel. Skipping them matters more than it looks: with the outgoing push
                    # set to zero there is nothing to overwrite a ripple seeded here, so the
                    # line being left behind would still visibly move.
                    continue
                if 0 < abs(index - current) <= LYRICS_WAVE_REACH:
                    self._lyrics_line_springs[index] = [LYRICS_WAVE_PX, 0.0]
        # The incoming line starts below its resting place and springs up through it.
        self._lyrics_line_springs[current] = [LYRICS_LINE_LIFT_PX, 0.0]
        if previous >= 0 and previous != current and LYRICS_LINE_PUSH_PX > 0.0:
            self._lyrics_line_springs[previous] = [-LYRICS_LINE_PUSH_PX, 0.0]

    # ------------------------------------------------------------------
    # Backend-agnostic playback helpers
    # ------------------------------------------------------------------
    def _playback_position(self) -> int:
        if self._audio_backend == "pcm" and self._engine is not None:
            return self._engine.position_ms()
        if self._player is not None:
            return self._player.position()
        return 0

    def _start_playback(self) -> None:
        if not self._current_track:
            return
        if self._audio_backend == "pcm" and self._engine is not None:
            self._engine.play()
            self._set_is_playing(True)
        elif self._player is not None:
            self._player.play()  # _is_playing follows via playbackStateChanged

    def _pause_playback(self) -> None:
        if self._audio_backend == "pcm" and self._engine is not None:
            self._engine.pause()
            self._set_is_playing(False)
        elif self._player is not None:
            self._player.pause()

    def _seek_to(self, ms: float) -> None:
        ms = max(0, int(ms))
        if self._audio_backend == "pcm" and self._engine is not None:
            self._engine.seek(ms)
        elif self._player is not None:
            self._player.setPosition(ms)

    def _set_volume(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if self._audio_backend == "pcm" and self._engine is not None:
            self._engine.set_volume(value)
        elif self._audio_output is not None:
            self._audio_output.setVolume(value)

    def _set_is_playing(self, value: bool) -> None:
        value = bool(value)
        if value == self._is_playing:
            return
        self._is_playing = value
        self._sync_rhythm_timer()
        self.update()

    # ------------------------------------------------------------------
    # Music rhythm, shared with other pages
    # ------------------------------------------------------------------
    def _rhythm_tick(self) -> None:
        """Analysis frame for times when the page's own animation timer is off."""
        self._update_music_reactivity(16.0)

    def _sync_rhythm_timer(self) -> None:
        """Run the second analysis driver exactly while hidden and playing."""
        wanted = self._is_playing and not self._page_visible
        if wanted and not self._rhythm_timer.isActive():
            self._rhythm_timer.start()
        elif not wanted and self._rhythm_timer.isActive():
            self._rhythm_timer.stop()

    def music_rhythm(self) -> "tuple[float, float]":
        """(loudness, beat impulse) of what is playing, for another page to borrow.

        Both are zero when nothing is playing, so a page that only borrows the
        rhythm (the dashboard's checker floor) goes back to its own idle motion
        instead of freezing at whatever the last analysed frame happened to be.
        """
        if not self._is_playing:
            return 0.0, 0.0
        return (
            max(0.0, min(1.2, self._music_level)),
            max(0.0, min(1.0, self._beat_impulse)),
        )

    def _play_pause(self) -> None:
        if not self._current_track:
            return
        if self._is_playing:
            self._pause_playback()
        else:
            self._start_playback()

    def _previous_track(self) -> None:
        if not self._playlist:
            return
        self._playlist_index = (self._playlist_index - 1) % len(self._playlist)
        self._load_track(
            self._playlist[self._playlist_index], auto_play=self._is_playing
        )

    def _next_track(self) -> None:
        if not self._playlist:
            return
        self._playlist_index = (self._playlist_index + 1) % len(self._playlist)
        self._load_track(
            self._playlist[self._playlist_index], auto_play=self._is_playing
        )

    def _on_position_changed(self, position: int) -> None:
        if self._audio_backend == "pcm":
            return  # the PCM engine drives the progress bar from the tick
        if self._progress_slider.dragging:
            return
        if self._duration > 0:
            self._progress_slider.set_target(position / self._duration)

    def _on_duration_changed(self, duration: int) -> None:
        self._duration = duration

    def _on_state_changed(self, state) -> None:
        self._set_is_playing(
            bool(
                self._audio_backend == "qt"
                and self._player
                and state == QMediaPlayer.PlayingState
            )
        )

    def _on_media_status_changed(self, status) -> None:
        if self._player is None or self._audio_backend != "qt":
            return
        if status == QMediaPlayer.EndOfMedia:
            self._next_track()

    def _on_engine_ready(self, duration_ms: int) -> None:
        if duration_ms > 0:
            self._duration = duration_ms

    def _on_engine_failed(self) -> None:
        """PCM decode/output failed for this track: fall back to QMediaPlayer."""
        if self._audio_backend != "pcm":
            return
        self._audio_backend = "qt"
        was_playing = self._is_playing
        self._set_is_playing(False)
        if self._player is not None and self._current_track:
            if was_playing:
                self._player.play()
            else:
                self._player.pause()

    def _on_engine_finished(self) -> None:
        if self._audio_backend == "pcm":
            self._next_track()

    def _on_metadata_changed(self) -> None:
        if self._player is None or QMediaMetaData is None:
            return
        meta = self._player.metaData()
        title = meta.value(QMediaMetaData.Title)
        artist = meta.value(QMediaMetaData.ContributingArtist)
        album = meta.value(QMediaMetaData.AlbumTitle)
        if title:
            self._song_title = _meta_text(title)
        if artist:
            self._song_artist = _meta_text(artist)
        if album:
            self._album = _meta_text(album)

        # Try to use embedded cover art if available. A container cover (an
        # unpacked ncm) wins: the stream we play carries no art, so trusting
        # the player here would replace a real cover with the placeholder.
        cover = None
        if self._container_cover is None:
            cover = meta.value(QMediaMetaData.CoverArtImage)
            if cover is None:
                cover = meta.value(QMediaMetaData.ThumbnailImage)
        if isinstance(cover, QPixmap):
            self._cover = cover
            self._cover_path = self._current_track
        elif isinstance(cover, QImage):
            self._cover = QPixmap.fromImage(cover)
            self._cover_path = self._current_track
        elif self._container_cover is not None:
            self._cover = self._container_cover
            self._cover_path = self._current_track
        self._update_vinyl_label_color()
        self._apply_music_palette(
            ColorExtractor.extract_palette(self._cover, count=5)
        )
        self.update()

    def _apply_music_palette(self, palette: list) -> None:
        """Adopt a new cover palette; the checkerboard re-tints from it."""
        self._music_palette = list(palette)
        self.update()

    def _update_music_reactivity(self, dt_ms: float) -> None:
        """Analyse the playing audio so the background moves with the music.

        With the PCM engine active this reads real samples around the playhead
        and derives loudness, bass energy and beat onsets. Analysis runs at
        ~30 Hz and the result is HELD until the next analysis — the synthetic
        fallback only applies when there is no PCM backend at all, never in
        between (alternating targets made the blobs flicker).
        """
        self._beat_impulse *= math.exp(-dt_ms / 130.0)
        self._beat_cool = max(0.0, self._beat_cool - dt_ms)

        use_pcm = (
            self._audio_backend == "pcm"
            and self._engine is not None
            and self._is_playing
        )
        if use_pcm:
            self._analyze_frame += 1
            if self._analyze_frame % 2 == 0:
                level, bass = self._analyse_pcm_window()
                if level is not None:
                    self._target_level = level
                    self._target_bass = bass
                # (None → not enough decoded data yet; keep previous targets)
        elif self._is_playing:
            # Synthetic pulse for the Qt fallback backend.
            self._music_phase += 0.085
            self._target_level = 0.32 + 0.22 * math.sin(self._music_phase)
            self._target_bass = 0.30 + 0.28 * math.sin(self._music_phase * 0.5)
        else:
            # Paused: relax to a calm idle glow instead of freezing.
            self._target_level = 0.16
            self._target_bass = 0.10

        follow = min(1.0, dt_ms / 140.0)
        self._music_level += (self._target_level - self._music_level) * follow
        self._music_bass += (self._target_bass - self._music_bass) * min(
            1.0, dt_ms / 220.0
        )

    def _analyse_pcm_window(self) -> tuple:
        """Return (loudness, bass) in 0..1 from PCM around the playhead."""
        data = self._engine.read_playhead_pcm(4096)
        samples = array("h")
        samples.frombytes(data[: 4096 * 4])
        if len(samples) < 512:
            return None, None
        lefts = samples[::2]
        if len(lefts) > 2048:
            lefts = lefts[::2]  # decimate for speed

        # Overall loudness with an adaptive peak follower so quiet tracks
        # still read as lively.
        acc = 0
        for s in lefts:
            acc += s * s
        rms = math.sqrt(acc / len(lefts)) / 32768.0
        self._lvl_peak = max(rms, self._lvl_peak * 0.9995, 0.05)
        level = max(0.0, min(1.15, rms / self._lvl_peak))

        # Bass via a one-pole low-pass (~150 Hz at the decimated rate).
        step = 4
        alpha = 0.10
        lp = 0.0
        b_acc = 0.0
        b_count = 0
        for i in range(0, len(lefts), step):
            lp += alpha * (lefts[i] - lp)
            b_acc += lp * lp
            b_count += 1
        bass_rms = math.sqrt(b_acc / max(1, b_count)) / 32768.0
        bass = max(0.0, min(1.2, bass_rms / (self._lvl_peak * 0.85)))

        # Beat detection: sudden loudness above the running average.
        self._beat_avg += (level - self._beat_avg) * 0.055
        if level > self._beat_avg * 1.28 + 0.06 and self._beat_cool <= 0.0:
            self._beat_impulse = 1.0
            self._beat_cool = 170.0
        return level, bass

    def _tick(self) -> None:
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        self._update_music_reactivity(16.0)

        # The checkerboard drifts toward the viewer; music energy speeds up
        # the scroll, bass makes it feel heavier, beats give it a kick.
        level = max(0.0, min(1.2, self._music_level))
        scroll_rate = 0.20 + 0.85 * level
        self._checker_offset += 0.016 * scroll_rate * (1.0 + 0.3 * self._beat_impulse)

        # 音乐色彩 clocks: the two haze swirls turn in place and the bubbles sway,
        # each on its own slow rhythm. The swirls' spin is deliberately NOT
        # music-reactive (they turn slowly, full stop); the bubbles only get a nudge.
        self._color_spin += 16.0 * COLOR_SHAPE_SPIN_DEG_PER_S / 1000.0
        self._bubble_clock += 16.0 * COLOR_BUBBLE_SWAY_RAD_PER_MS * (
            1.0 + COLOR_BUBBLE_SWAY_SPEEDUP * min(1.0, level)
        )
        # The palette mist wanders on its own slow clock, at a fixed speed: it is
        # the background, so it should not twitch with the music.
        self._color_mist_phase += 16.0 * COLOR_MIST_DRIFT_RAD_PER_S / 1000.0

        # Grain offset, re-rolled at roughly film speed instead of every frame.
        self._noise_clock += 16.0
        if self._noise_clock >= COLOR_NOISE_STEP_MS:
            self._noise_clock = 0.0
            drift = max(1, COLOR_NOISE_DRIFT_PX)
            self._noise_offset = QPoint(
                random.randint(-drift, drift), random.randint(-drift, drift)
            )

        # 音乐色彩 composite refresh clock (see _draw_music_colors).
        self._color_frame_clock += 16.0
        self._color_settle_clock += 16.0

        # Update elastic sliders and speaker-icon bounce.
        self._progress_slider.update()
        self._volume_slider.update()
        self._update_volume_icon_physics()

        # Smoothly follow the active lyric, or honor a manual scroll.
        self._update_lyrics_scroll()

        # Frame-rate independent vinyl rotation and scratch audio sync.
        dt_ms = max(0.0, min(self._tick_elapsed_timer.restart(), 100.0))

        # Advance the motion a line change starts. Timed from the frame delta so the springs
        # behave the same at any refresh rate.
        self._update_lyrics_fade(dt_ms)
        self._update_lyrics_line_springs(dt_ms)

        # Marquee the title / artist+album lines when they overflow their column.
        self._update_info_scroll(dt_ms)

        # Fade the "lyric copied" flash. Exponential so the first frames are
        # bright and the tail is soft, rather than a linear ramp that looks like
        # a stuck highlight for its last third. The cutoff is deliberately well
        # below visibility (see LYRICS_COPY_FLASH_CUTOFF): dropping it earlier
        # pops, because the flash is still clearly brighter at that point.
        if self._lyric_copy_flash > 0.0:
            self._lyric_copy_flash *= math.exp(-dt_ms / LYRICS_COPY_FLASH_TAU_MS)
            if self._lyric_copy_flash < LYRICS_COPY_FLASH_CUTOFF:
                self._lyric_copy_flash = 0.0
                self._lyric_copy_flash_index = -1

        # Soft jelly wobble for freshly pressed transport buttons.
        self._update_button_press(dt_ms)

        # Ease the scratch lift so the record rises/falls instead of popping.
        lift_target = VINYL_DRAG_LIFT_SCALE if self._vinyl_dragging else 1.0
        self._vinyl_lift += (lift_target - self._vinyl_lift) * min(
            1.0, dt_ms / VINYL_LIFT_EASE_MS
        )

        if self._audio_backend == "pcm" and self._engine is not None:
            self._update_pcm_turntable(dt_ms)
        else:
            self._update_qt_turntable(dt_ms)

        self.update()

    def _update_qt_turntable(self, dt_ms: float) -> None:
        """Original QMediaPlayer turntable: visual angle + loose sync."""
        if self._is_playing and not self._vinyl_dragging:
            self._vinyl_angle = (
                self._vinyl_angle + VINYL_SPIN_DEG_PER_MS * dt_ms
            ) % 360
        elif not self._vinyl_dragging:
            self._vinyl_angle = (
                self._vinyl_angle + self._vinyl_angular_velocity * dt_ms
            ) % 360
            self._vinyl_angular_velocity *= math.exp(
                -dt_ms / VINYL_INERTIA_TAU_MS
            )
            if abs(self._vinyl_angular_velocity) < 0.001:
                self._vinyl_angular_velocity = 0.0

        # Scratch: modulate playback speed while dragging and keep the playhead
        # loosely synced to the record angle. Qt multimedia cannot play
        # backwards, so reverse drags rely on low forward speed plus seeks.
        if (
            self._vinyl_scratch_engaged
            and self._player is not None
            and self._duration > 0
        ):
            desired_ms = self._desired_scratch_position()
            speed = self._scratch_rate_from_velocity(
                self._vinyl_angular_velocity
            )
            self._player.setPlaybackRate(speed)
            drift = self._player.position() - desired_ms
            forward_threshold = min(
                VINYL_FORWARD_LAG_MS,
                VINYL_FORWARD_DRIFT_BASE_MS
                + abs(self._vinyl_angular_velocity) * 400.0,
            )
            if self._vinyl_angular_velocity < 0 and drift > VINYL_BACKWARD_DRIFT_MS:
                self._player.setPosition(desired_ms)
            elif drift > forward_threshold or drift < -VINYL_FORWARD_LAG_MS:
                self._player.setPosition(desired_ms)
        elif self._player is not None:
            self._return_rate_to_normal(dt_ms)
        self._vinyl_display_velocity = self._vinyl_angular_velocity

    def _update_pcm_turntable(self, dt_ms: float) -> None:
        """PCM engine turntable: the record angle IS the playhead.

        A real record's groove position and rotation are the same thing, so
        instead of patching drift we always derive the angle from the engine
        playhead. Scratching writes the playhead straight from the hand; the
        engine's release easing then spins it back up to 1x.
        """
        engine = self._engine
        # Only drive the playhead once the scratch has actually ENGAGED. A press
        # arms the grab but does not engage it until the pointer moves, so this
        # must not test `_vinyl_dragging` alone: during that window the target is
        # still anchored to the previous grab's position, and writing it here
        # yanked the playhead backwards -- the audio kept advancing while the
        # hand was merely resting on the record, and each write undid it.
        if self._vinyl_scratch_engaged:
            # The angle is driven directly by the mouse (mouseMoveEvent);
            # keep the playhead glued to the record so the audio pump writes
            # exactly what the needle reads.
            engine.set_playhead_ms(self._desired_scratch_position_raw())
            self._vinyl_display_velocity = self._vinyl_angular_velocity
            return

        if self._is_playing:
            # Release inertia lives in the engine's speed easing; re-sync the
            # display velocity to it and let any paused-coast offset decay.
            self._angle_offset_ms *= math.exp(-dt_ms / 120.0)
            self._vinyl_angular_velocity = (
                engine.speed() * VINYL_SPIN_DEG_PER_MS
            )
        elif abs(self._vinyl_angular_velocity) > 0.001:
            # Coast visually after a release while paused (no audio moves).
            self._angle_offset_ms += (
                self._vinyl_angular_velocity * VINYL_MS_PER_DEG * dt_ms
            )
            self._vinyl_angular_velocity *= math.exp(
                -dt_ms / VINYL_INERTIA_TAU_MS
            )
            if abs(self._vinyl_angular_velocity) < 0.001:
                self._vinyl_angular_velocity = 0.0
        self._vinyl_display_velocity = self._vinyl_angular_velocity

        angle = (engine.position_ms() + self._angle_offset_ms) / VINYL_MS_PER_DEG
        self._vinyl_angle = angle % 360.0

        if not self._progress_slider.dragging and self._duration > 0:
            self._progress_slider.set_target(
                self._playback_position() / self._duration
            )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1) Cover-colored, music-reactive background in the chosen
        #    visualisation (可视化效果).
        self._draw_background(painter, w, h)

        # 2) Tinted panels over the background keep the UI readable. The tint is
        #    the page's biggest brightness lever: see PAGE_TINT_* in constants.
        tint = self._page_tint()
        if self._switching and self._ui_switch_pix is not None:
            # Use the cached UI snapshot so we don't re-render the whole UI
            # every frame during the squeeze animation.
            painter.drawPixmap(0, 0, w, h, self._ui_switch_pix)
        else:
            self._draw_ui_layer(painter, w, h, tint)

    def _checker_colors(self) -> tuple:
        """(cell, field, glow) colors derived from the current cover palette."""
        palette = self._music_palette
        if palette:
            cell = QColor(palette[0])
            field = QColor(palette[min(1, len(palette) - 1)])
            glow = QColor(palette[min(2, len(palette) - 1)])
        else:
            # Brand fallback.
            cell = QColor(118, 185, 0)
            field = QColor(46, 92, 28)
            glow = QColor(170, 220, 90)

        # Darken toward a background tone so the UI stays readable on top. Lifted
        # a little from the original 0.42 / 0.16: measured, the checkerboard's own
        # backdrop sat at luma ~10, which is what made the page read as dark long
        # before the 音乐色彩 effect existed.
        cell = ColorExtractor.darken_color(cell, 0.52, 0.85)
        field = ColorExtractor.darken_color(field, 0.22, 0.55)
        glow = ColorExtractor.darken_color(glow, 0.55, 0.85)
        return cell, field, glow

    def _draw_background(self, painter: QPainter, w: int, h: int) -> None:
        """Paint the background visualisation picked in 可视化效果."""
        if self._visualizer == _VISUALIZER_COLORS:
            self._draw_music_colors(painter, w, h)
        else:
            self._draw_checker(painter, w, h)

    @staticmethod
    def _page_tint() -> QColor:
        """The veil drawn over the whole background (PAGE_TINT_* in constants)."""
        return QColor(*PAGE_TINT_COLOR, PAGE_TINT_ALPHA)

    # ------------------------------------------------------------------
    # 音乐色彩: the palette mist, its swirls, its drops and the frosted sheet
    # ------------------------------------------------------------------
    def _mist_layers(self, w: int, h: int) -> QPixmap:
        """The frosted sheet over the mist, cached -- palette mist, no cover.

        The 音乐色彩 background is the cover's *colours* rather than the cover
        picture -- deliberately only the basic colours, hazy -- so this sheet is
        the same blob field, softer, with the readability veil baked in. That also
        makes it cheap: the field is drawn tiny and upscaled, where the blurred
        cover it replaces needed two cached blur passes.

        Everything here is at LOGICAL resolution, matching the composite that draws
        it (see `_paint_music_colors`).
        """
        key = (w, h, self._mist_palette_key())
        if key == self._color_cache_key and self._color_layers[0] is not None:
            return self._color_layers[0]

        soft = self._color_mist(w, h, COLOR_BG_BLUR_DIVISOR)
        frost = QPixmap(soft)
        veil = QPainter(frost)
        veil.fillRect(0, 0, w, h, QColor(8, 10, 14, COLOR_FROST_DARKEN))
        veil.end()

        self._color_cache_key = key
        self._color_layers = (frost,)
        return frost

    def _mist_palette_key(self) -> tuple:
        """Cache key for the mist: the palette it is painted from."""
        return tuple(colour.rgb() for colour in self._music_palette)

    def _mist_colours(self) -> list:
        """The colours the mist is made of: the cover's palette, or a fallback.

        The palette comes from `ColorExtractor.extract_palette` and can be empty
        (a cover with nothing saturated in it), in which case the page keeps a
        neutral cool wash instead of turning black.
        """
        colours = [QColor(c) for c in self._music_palette]
        if colours:
            return colours
        return [QColor(45, 50, 70), QColor(28, 32, 46), QColor(60, 66, 88)]

    def _color_mist(self, w: int, h: int, divisor: float, phase: float = 0.0) -> QPixmap:
        """A soft field of the palette's colours, with no cover detail at all.

        Big blobs of the extracted colours on a dark base, drifting slowly (blob
        positions come from *phase*, which the page's tick advances). Drawn at
        1/divisor of the page and smoothly scaled up: that upscale is the whole
        blur, which is why this can afford to be rebuilt every frame while the
        real blur passes it replaces could not.
        """
        mw = max(6, int(w / max(1.0, float(divisor))))
        mh = max(4, int(h / max(1.0, float(divisor))))
        colours = self._mist_colours()
        # The gaps between blobs take the palette's own darkest tone rather than a
        # fixed near-black: that is what the cover's shadowed areas contributed,
        # and without it the field reads grey (measured: 65% of the old brightness).
        base = min(
            colours,
            key=lambda c: 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue(),
        )
        mist = QPixmap(mw, mh)
        mist.fill(base)
        painter = QPainter(mist)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        for index in range(max(1, COLOR_MIST_BLOBS)):
            colour = QColor(colours[index % len(colours)])
            colour.setAlpha(COLOR_MIST_BLOB_ALPHA)
            # Spread the blobs over the page and give each its own slow orbit, so
            # the field never looks like one picture sliding sideways.
            angle = index * 2.399963  # golden angle: an even, non-repeating spread
            base_x = 0.5 + 0.42 * math.cos(angle)
            base_y = 0.5 + 0.34 * math.sin(angle)
            drift_x = COLOR_MIST_DRIFT_X * math.sin(phase * 0.9 + index * 1.7)
            drift_y = COLOR_MIST_DRIFT_Y * math.cos(phase * 1.1 + index * 2.3)
            radius = COLOR_MIST_BLOB_SIZE * (
                1.0 + COLOR_MIST_BREATHE * math.sin(phase * 0.7 + index)
            )
            cx = (base_x + drift_x) * mw
            cy = (base_y + drift_y) * mh
            r = max(1.0, radius * max(mw, mh))
            gradient = QRadialGradient(QPointF(cx, cy), r)
            gradient.setColorAt(0.0, colour)
            edge = QColor(colour)
            edge.setAlpha(0)
            gradient.setColorAt(1.0, edge)
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.fillRect(0, 0, mw, mh, QColor(8, 10, 14, COLOR_BACKDROP_DARKEN))
        painter.end()
        return mist.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def _color_slab_frames(self, w: int, h: int) -> list:
        """(cx, cy, radius, tilt, spin_scale) for the two slabs, in page pixels.

        The slabs are anchored to the drawing's two black discs and never
        translate, so unlike the bubbles there is nothing to solve here -- only
        the page's fractions to turn back into pixels. They are deliberately NOT
        clamped: the drawing has them cut by the frame, and their centres are off
        the page by design.
        """
        reach = min(w, h)
        return [
            (cx * w, cy * h, radius * reach, tilt, spin_scale)
            for cx, cy, radius, tilt, spin_scale in _COLOR_SLABS
        ]

    def _color_bubble_placements(self, w: int, h: int) -> list:
        """Where each bubble floats this rebuild: (x, y, radius) in page pixels.

        Two things move a bubble: a slow Lissajous wander (its own phase and its
        own speed per bubble, so the school never marches in step) and, after
        that, the containment -- a bubble is pushed back out of either slab and
        pulled back inside the page. The drawing keeps the whole school in the
        clear band between the two discs, and that has to hold for the whole
        wander rather than only at rest, so it is enforced here rather than left
        to the amplitudes above.

        Deterministic and continuous in the sway clock, and the push only ever
        moves a bubble that is already inside a slab's clearance, so nothing pops.
        """
        reach = min(w, h)
        clearance = COLOR_BUBBLE_CLEARANCE * reach
        slabs = self._color_slab_frames(w, h)
        bubbles = []
        for index, (cx, cy, radius_ratio) in enumerate(_COLOR_BUBBLES):
            radius = radius_ratio * reach
            phase = index * 2.399963  # golden angle: no two bubbles in step
            speed = 1.0 + 0.35 * math.sin(phase * 1.7)
            wander = 1.0 + 0.35 * math.sin(phase * 0.9)
            x = (
                cx
                + COLOR_BUBBLE_SWAY_X
                * wander
                * math.sin(self._bubble_clock * speed + phase)
            ) * w
            y = (
                cy
                + COLOR_BUBBLE_SWAY_Y
                * wander
                * math.cos(self._bubble_clock * speed * 0.83 + phase * 1.3)
            ) * h
            bubbles.append([x, y, radius])

        for _ in range(4):
            for bubble in bubbles:
                for slab_x, slab_y, slab_radius, _tilt, _spin in slabs:
                    delta_x = bubble[0] - slab_x
                    delta_y = bubble[1] - slab_y
                    distance = math.hypot(delta_x, delta_y)
                    need = slab_radius + bubble[2] + clearance
                    if distance < need:
                        if distance < 0.001:  # dead centre: pick any direction
                            delta_x, delta_y, distance = 1.0, 0.0, 0.001
                        scale = need / distance
                        bubble[0] = slab_x + delta_x * scale
                        bubble[1] = slab_y + delta_y * scale
                bubble[0] = min(max(bubble[0], bubble[2]), w - bubble[2])
                bubble[1] = min(max(bubble[1], bubble[2]), h - bubble[2])
        return [tuple(bubble) for bubble in bubbles]


    def _draw_music_colors(self, painter: QPainter, w: int, h: int) -> None:
        """Blit the cached 音乐色彩 composite, then the grain on top of it.

        Building the layers live costs ~14.5 ms a frame at 1920x1200 device
        pixels, which is most of a 60 fps budget before the UI layer is even
        drawn -- and a translucent child like the music menu makes the page
        repaint its whole background on every frame of its own animation, which
        is exactly where the lag was noticed. Nothing in the effect moves fast
        enough to need 60 Hz, so it is rebuilt every COLOR_FRAME_STEP_MS and
        blitted (upscaled from logical resolution) in between: measured, that is
        0.96 ms p50 instead of 14.5 ms.

        The grain is drawn AFTER that blit, at device resolution, so its dots stay
        one physical pixel instead of being doubled by the upscale.

        A SIZE change is treated differently from a cover change: while the window
        is being dragged bigger or smaller the size changes every frame, and
        rebuilding there costs the blur layers (~17 ms) plus the composite (~9 ms)
        per frame -- which is what made resizing the window feel stuck on this
        effect. The composite we already have is stretched instead, and rebuilt
        once the size has held still for COLOR_RESIZE_SETTLE_MS.
        """
        key = (w, h, self._cover.cacheKey())
        cover_changed = self._color_frame_key is None or self._color_frame_key[2] != key[2]
        if key != self._color_frame_key:
            if self._color_size_seen != (w, h):
                self._color_size_seen = (w, h)
                self._color_settle_clock = 0.0
            if cover_changed or self._color_settle_clock >= COLOR_RESIZE_SETTLE_MS:
                self._color_frame = self._paint_music_colors(w, h)
                self._color_frame_key = key
                self._color_frame_clock = 0.0
        elif self._color_frame_clock >= COLOR_FRAME_STEP_MS:
            self._color_frame = self._paint_music_colors(w, h)
            self._color_frame_clock = 0.0

        frame = self._color_frame
        if frame is None:  # first frame ever: nothing to stretch
            frame = self._color_frame = self._paint_music_colors(w, h)
            self._color_frame_key = key
            self._color_frame_clock = 0.0
        if frame.width() == w and frame.height() == h:
            painter.drawPixmap(0, 0, frame)
        else:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(
                QRectF(0, 0, w, h),
                frame,
                QRectF(0, 0, frame.width(), frame.height()),
            )
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

        # Film grain. A texture brush rather than a loop of blits, and the offset
        # is only re-rolled a few times a second (see _tick): re-randomising it
        # every frame shook the whole frosted layer.
        noise = QBrush(self._noise_pixmap())
        shift = QTransform()
        shift.translate(self._noise_offset.x(), self._noise_offset.y())
        noise.setTransform(shift)
        painter.fillRect(0, 0, w, h, noise)

    def _paint_music_colors(self, w: int, h: int) -> QPixmap:
        """Render the whole effect into a logical-resolution pixmap (see above)."""
        frame = QPixmap(w, h)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_music_color_layers(painter, w, h)
        painter.end()
        return frame

    def _paint_music_color_layers(self, painter: QPainter, w: int, h: int) -> None:
        """Only the palette mist, with two soft swirls and a school of drops in it.

        The user asked for the background to be the cover's basic colours as haze,
        and then for the glass slabs and the bubbles to melt into that haze and for
        the light strands to go away. So there are no more rims, no clipped fills
        and no highlights: what is left is the drifting mist, two large oval patches
        of slightly denser haze turning slowly in place, and the bubbles as faint
        round lifts drifting between them -- then the frosted sheet, which is what
        keeps the UI readable, and film grain.
        """
        backdrop = self._color_mist(w, h, COLOR_MIST_DIVISOR, self._color_mist_phase)
        frost = self._mist_layers(w, h)
        _cell_c, _field_c, glow_c = self._checker_colors()
        flash = min(1.0, self._beat_impulse * 0.9)

        painter.setPen(Qt.NoPen)
        painter.drawPixmap(0, 0, backdrop)

        # The two slabs, melted in: a soft oval patch of denser fog at each anchor,
        # turning slowly about its own centre. With no rim to give the shape away,
        # the slow turn is carried by the oval's tilt -- which is why it is an oval
        # and not a circle (a circle turning looks completely static).
        for cx, cy, radius, tilt, spin_scale in self._color_slab_frames(w, h):
            spin = self._color_spin * spin_scale
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(tilt + spin)
            painter.translate(-cx, -cy)
            patch = QRadialGradient(QPointF(cx, cy), max(24.0, radius))
            patch.setColorAt(0.0, QColor(255, 255, 255, COLOR_SHAPE_MIST_ALPHA))
            patch.setColorAt(
                0.55, QColor(255, 255, 255, int(COLOR_SHAPE_MIST_ALPHA * 0.5))
            )
            patch.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(patch)
            painter.drawEllipse(
                QPointF(cx, cy), radius * 1.08, radius * 0.86
            )
            painter.restore()

        # The bubbles, likewise: a faint round lift with no rim and no highlight, so
        # they read as denser beads of the same fog rather than as objects in it.
        for x, y, radius in self._color_bubble_placements(w, h):
            drop = QRadialGradient(QPointF(x, y), max(4.0, radius))
            drop.setColorAt(0.0, QColor(255, 255, 255, COLOR_BUBBLE_MIST_ALPHA))
            drop.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(drop)
            painter.drawEllipse(QPointF(x, y), radius, radius)

        # Frosted sheet over everything behind it. A beat lets a little colour
        # flash through the frost, which keeps the backdrop feeling alive.
        painter.setOpacity(
            max(0.0, min(1.0, COLOR_FROST_ALPHA / 255.0 - 0.10 * flash))
        )
        painter.drawPixmap(0, 0, frost)
        painter.setOpacity(1.0)

    def _noise_pixmap(self) -> QPixmap:
        """A tile of two-sided film grain, cached (used as a texture brush).

        Built at DEVICE resolution and tagged with the ratio, so the grain lands
        on single physical pixels: at this machine's 200% scaling a logical-pixel
        tile draws every dot as a 2x2 block, which reads as coarse noise rather
        than as grain.
        """
        if self._noise_tile is not None:
            return self._noise_tile
        ratio = max(1.0, float(self.devicePixelRatioF()))
        size = max(8, int(COLOR_NOISE_TILE * ratio))
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        for x in range(size):
            for y in range(size):
                level = random.gauss(0.0, 1.0) * COLOR_NOISE_ALPHA
                alpha = min(255, int(abs(level)))
                if alpha <= 2:
                    continue
                shade = 255 if level > 0 else 0
                image.setPixel(x, y, (alpha << 24) | (shade << 16) | (shade << 8) | shade)
        sprite = QPixmap.fromImage(image)
        sprite.setDevicePixelRatio(ratio)
        self._noise_tile = sprite
        return self._noise_tile

    def _draw_checker(self, painter: QPainter, w: int, h: int) -> None:
        """Full-page perspective checkerboard that reacts to the music.

        - Colors come from the album cover palette (change tracks -> re-tint).
        - Music energy brightens the cells; bass deepens the field color.
        - Beats flash the glow color; the floor scrolls with the music energy.
        """
        cell_c, field_c, glow_c = self._checker_colors()
        level = max(0.0, min(1.2, self._music_level))
        bass = max(0.0, min(1.2, self._music_bass))

        def scaled(color: QColor, factor: float, sat_boost: float = 0.0) -> QColor:
            c = QColor(color)
            c.setRed(max(0, min(255, int(c.red() * factor))))
            c.setGreen(max(0, min(255, int(c.green() * factor))))
            c.setBlue(max(0, min(255, int(c.blue() * factor))))
            if sat_boost > 0.0:
                h_, s_, v_, a_ = c.getHsvF()
                s_ = min(1.0, s_ + sat_boost)
                c.setHsvF(h_, s_, v_, a_)
            return c

        # Field base: bass deepens (darkens) the non-cell background.
        field = scaled(field_c, 1.0 - 0.22 * min(1.0, bass))
        painter.setPen(Qt.NoPen)
        painter.setBrush(field)
        painter.drawRect(0, 0, w, h)

        # Cells: brightness follows the music energy, plus a beat flash that
        # tints them toward the glow color.
        bright = 0.85 + 0.55 * level
        flash = min(1.0, self._beat_impulse * 0.9)
        cell = scaled(cell_c, bright)
        if flash > 0.01:
            cell = _blend_color(cell, glow_c, flash * 0.55)

        rows = 14
        cols = 10
        # Perspective: rows compress toward the far (top) edge.
        spread = 2.4  # horizontal spread at the near edge (screen widths)
        offset = self._checker_offset % 2.0

        painter.setBrush(cell)
        for row in range(rows):
            # Row depth in 0..1 (0 = far/top, 1 = near/bottom).
            f0 = (row + offset) / rows
            f1 = (row + 1 + offset) / rows
            y0 = h * (f0 ** 2.2)
            y1 = h * (min(f1, 1.0 + 1.0 / rows) ** 2.2)
            if y0 >= h:
                continue
            y1 = min(y1, h)
            # Perspective horizontal scale: small at the far edge, wide near.
            s0 = 0.12 + 1.28 * min(1.0, f0) ** 1.6
            s1 = 0.12 + 1.28 * min(1.0, f1) ** 1.6
            # Farther rows fade slightly into the field color.
            depth_alpha = max(0.0, min(1.0, 0.25 + 0.75 * min(1.0, f0 * 1.4)))
            row_color = _blend_color(field, cell, depth_alpha)

            for col in range(cols + 2):
                if (row + col) % 2:
                    continue
                u0 = col / cols - 0.5 - 0.1
                u1 = (col + 1) / cols - 0.5 - 0.1
                poly = QPolygonF(
                    [
                        QPointF(w / 2 + u0 * w * spread * s0, y0),
                        QPointF(w / 2 + u1 * w * spread * s0, y0),
                        QPointF(w / 2 + u1 * w * spread * s1, y1),
                        QPointF(w / 2 + u0 * w * spread * s1, y1),
                    ]
                )
                painter.setBrush(row_color)
                painter.drawPolygon(poly)

    def _has_lyrics(self) -> bool:
        return bool(self._lyrics)

    def _draw_ui_layer(
        self, painter: QPainter, w: int, h: int, tint: QColor
    ) -> None:
        # Animated split between player and lyrics panels.
        progress = self._lyrics_progress
        split = 0.5 * progress
        left_w = int(w * (1.0 - split))
        right_w = w - left_w
        left_panel = QRect(0, 0, left_w, h)
        right_panel = QRect(left_w, 0, right_w, h)
        painter.fillRect(left_panel, tint)
        painter.fillRect(right_panel, tint)

        # The panel split used to carry a faint 1px white rule here (alpha 20,
        # fading in with the lyrics). The user asked for it to go: the two panels
        # already read as separate surfaces, so the line was only a seam.
        # Player UI on the left.
        self._draw_player(painter, left_panel)

        # Lyrics on the right, sliding in/out with the panel.
        if right_w > 40:
            self._draw_lyrics(painter, right_panel)

    def _render_ui_snapshot(self, w: int) -> QPixmap:
        """Render the UI layer at the reference size for scaled squeezing."""
        ref_h = max(1, self._switch_ref_h)
        pixmap = QPixmap(w, ref_h)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        tint = self._page_tint()
        # Don't let the scaled snapshot overwrite the hit-testing rects.
        old_play_rect = self._play_btn_rect
        old_folder_rect = self._folder_btn_rect
        old_progress_rect = self._progress_bar_rect
        old_volume_rect = self._volume_bar_rect
        self._draw_ui_layer(p, w, ref_h, tint)
        self._play_btn_rect = old_play_rect
        self._folder_btn_rect = old_folder_rect
        self._progress_bar_rect = old_progress_rect
        self._volume_bar_rect = old_volume_rect
        p.end()
        return pixmap

    # ------------------------------------------------------------------
    # Player UI
    # ------------------------------------------------------------------
    def _draw_player(self, painter: QPainter, rect: QRect) -> None:
        margin = 32
        content_w = rect.width() - margin * 2
        if content_w < 120:
            return

        # Center the whole player UI block horizontally, like the cover.
        col_w = min(content_w, 360)
        col_x = rect.left() + (rect.width() - col_w) // 2

        # Volume bar at the very bottom (nudged upward to balance the layout).
        vol_h = 6
        vol_y = rect.bottom() - margin - vol_h - 16
        self._draw_volume_bar(
            painter, col_x, vol_y, col_w, vol_h,
            self._volume_slider,
            (self._vol_icon_l_offset, self._vol_icon_r_offset),
        )
        self._volume_bar_rect = QRect(col_x, vol_y - 7, col_w, 20)

        # Playback buttons above the volume bar.
        btn_size = 36
        btn_gap = 24
        btn_y = vol_y - 16 - btn_size
        row_w = btn_size * 4 + btn_gap * 3
        btns_x = col_x + (col_w - row_w) // 2
        prev_rect = QRect(btns_x, btn_y, btn_size, btn_size)
        self._prev_btn_rect = prev_rect
        self._draw_button(painter, prev_rect, "previous")
        play_rect = QRect(btns_x + btn_size + btn_gap, btn_y, btn_size, btn_size)
        self._play_btn_rect = play_rect
        self._draw_button(painter, play_rect, "pause" if self._is_playing else "play")
        next_rect = QRect(
            btns_x + (btn_size + btn_gap) * 2, btn_y, btn_size, btn_size
        )
        self._next_btn_rect = next_rect
        self._draw_button(painter, next_rect, "next")

        # Folder/settings button at the right end of the button row.
        folder_rect = QRect(
            btns_x + (btn_size + btn_gap) * 3, btn_y, btn_size, btn_size
        )
        self._folder_btn_rect = folder_rect
        menu_kind = "menu" if self._music_dir else "folder"
        self._draw_button(painter, folder_rect, menu_kind)

        # Progress bar above the buttons, aligned with the button row.
        bar_h = 6
        bar_y = btn_y - 20 - bar_h
        self._draw_progress_bar(
            painter, btns_x, bar_y, row_w, bar_h, self._progress_slider
        )
        self._progress_bar_rect = QRect(btns_x, bar_y, row_w, bar_h)

        # Album cover and track info above the progress bar.
        info_h = 70
        gap = 24
        top_y = rect.top() + margin + 16
        max_cover_h = bar_y - gap - info_h - gap - top_y
        cover_size = min(col_w, 240, max(80, max_cover_h))
        cover_size = max(80, cover_size)
        cover_x = col_x + (col_w - cover_size) // 2
        cover_y = top_y
        self._draw_cover_and_vinyl(painter, cover_x, cover_y, cover_size)

        info_y = cover_y + cover_size + gap
        self._draw_track_info(painter, col_x, info_y, col_w)

    def _sleeve_pixmap(self, size: int, painter: QPainter) -> QPixmap:
        """The square sleeve, cut from the cover at DEVICE resolution.

        A sleeve pixmap built at the logical size (240) is stretched to 480
        physical pixels on this machine's 200% display, so the artwork carried
        half the detail it should -- which is what made it look soft next to the
        same file in another player. Measured with a 1px checkerboard as the
        cover, rendered through this page into a DPR=2 target: at device size the
        pattern survives intact (mean|dx| 255.0, identical to the cover scaled
        straight to 480px), while at logical size no pixel-to-pixel detail is
        left at all. With a real 500px cover photo the edge energy went 3.3 ->
        4.1, i.e. up to the ideal 4.1.

        The cache keeps the smooth resample off the 60 fps path: it used to
        rebuild and rescale the sleeve on every repaint.
        """
        ratio = max(1.0, float(painter.device().devicePixelRatioF()))
        key = (size, round(ratio, 3), self._cover.cacheKey())
        cached = self._sleeve_cache
        if cached is not None and cached[0] == key:
            return cached[1]

        dev = max(1, int(round(size * ratio)))
        sleeve = QPixmap(dev, dev)
        sleeve.setDevicePixelRatio(ratio)
        sleeve.fill(Qt.transparent)
        sp = QPainter(sleeve)
        sp.setRenderHint(QPainter.Antialiasing)

        sleeve_path = QPainterPath()
        sleeve_path.addRoundedRect(0, 0, size, size, 16, 16)
        sp.setClipPath(sleeve_path)
        scaled = self._cover.scaled(
            dev, dev, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        # Source rect spelled out: `scaled` carries no ratio of its own, so the
        # logical target rect has to be paired with its real device size.
        sp.drawPixmap(
            QRectF(0, 0, size, size),
            scaled,
            QRectF(0, 0, scaled.width(), scaled.height()),
        )
        sp.setClipping(False)

        # Sleeve border.
        sp.setPen(QPen(QColor(255, 255, 255, 45), 1))
        sp.setBrush(Qt.NoBrush)
        sp.drawRoundedRect(0, 0, size, size, 16, 16)
        sp.end()

        self._sleeve_cache = (key, sleeve)
        return sleeve

    def _draw_cover_and_vinyl(
        self, painter: QPainter, x: int, y: int, size: int
    ) -> None:
        """Draw the square sleeve with a sliding circular record."""
        if size < 16:
            return

        self._sleeve_rect = QRect(x, y, size, size)
        p = self._vinyl_out_progress
        cx = x + size / 2
        cy = y + size / 2
        # The vinyl is slightly smaller than the square sleeve.
        record_size = int(size * 0.84)
        record_r = record_size / 2 - 1
        lift = self._vinyl_lift

        # Groove sheen intensifies with scratch speed so fast drags visibly
        # blur the surface light.
        sheen_boost = 0.0
        if self._vinyl_dragging:
            sheen_boost = min(1.0, abs(self._vinyl_display_velocity) / 1.2)
        elif abs(self._vinyl_display_velocity) > VINYL_SPIN_DEG_PER_MS * 1.6:
            sheen_boost = 0.25  # fast release spin keeps a subtle sheen

        # Resting pose: the record peeks out from the sleeve's right edge by a
        # small sliver -- just enough to aim at. The sliver width is
        # `in_dx + record_r - size/2`, so in_dx solves to the expression below;
        # getting this backwards parks nearly the whole record outside.
        peek = record_size * VINYL_PEEK_FRACTION
        in_dx = size / 2 - record_r + peek
        in_dy = 0
        # Pulled out: the record sits centred on the cover.
        out_dx = 0.0
        out_dy = 0.0
        in_cx = cx + in_dx
        in_cy = cy + in_dy
        out_cx = cx + out_dx
        out_cy = cy + out_dy
        cur_cx = in_cx + (out_cx - in_cx) * p
        cur_cy = in_cy + (out_cy - in_cy) * p

        self._vinyl_record_center = QPointF(cur_cx, cur_cy)
        self._vinyl_record_radius = record_r * lift

        # Behind record (only its peeking sliver is visible while stowed).
        behind_alpha = max(0.0, 1.0 - p * 2.5)
        if behind_alpha > 0.01:
            painter.save()
            painter.setClipRect(
                QRectF(x, y, size + max(0.0, in_dx) + record_r, size)
            )
            painter.setOpacity(behind_alpha)
            self._draw_rotated_record(
                painter, int(in_cx - record_r), int(in_cy - record_r), record_size
            )
            painter.setOpacity(1.0)
            painter.restore()

        # Sleeve: plain square cover.
        painter.drawPixmap(x, y, self._sleeve_pixmap(size, painter))

        # Front record (slides out and sits on top of the sleeve).
        front_alpha = min(1.0, p * 2.5)
        lifted_r = record_r * lift
        if front_alpha > 0.01:
            painter.setOpacity(front_alpha)
            lifted_size = int(record_size * lift)
            lifted_r = lifted_size / 2 - 1
            self._draw_rotated_record(
                painter,
                int(cur_cx - lifted_r),
                int(cur_cy - lifted_r),
                lifted_size,
                label_tint=self._vinyl_label_color,
                label_text=self._song_title,
                sheen_boost=sheen_boost,
            )

            # Cursor light: a soft radial glow centered on the mouse,
            # only visible when hovering over the pulled-out record.
            dx = self._mouse.x() - cur_cx
            dy = self._mouse.y() - cur_cy
            hovering = dx * dx + dy * dy <= lifted_r * lifted_r
            if hovering:
                painter.save()
                clip = QPainterPath()
                clip.addEllipse(QPointF(cur_cx, cur_cy), lifted_r, lifted_r)
                painter.setClipPath(clip)
                light_grad = QRadialGradient(
                    self._mouse,
                    lifted_r * VINYL_HOVER_LIGHT_RADIUS_RATIO,
                )
                light_grad.setColorAt(
                    0.0, QColor(255, 255, 255, VINYL_HOVER_LIGHT_ALPHA)
                )
                light_grad.setColorAt(0.5, QColor(255, 255, 255, 22))
                light_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.setBrush(light_grad)
                painter.setPen(Qt.NoPen)
                painter.drawRect(
                    int(cur_cx - lifted_r),
                    int(cur_cy - lifted_r),
                    int(lifted_r * 2),
                    int(lifted_r * 2),
                )
                painter.restore()

            painter.setOpacity(1.0)

    def _draw_rotated_record(
        self,
        painter: QPainter,
        x: int,
        y: int,
        size: int,
        label_tint: QColor | None = None,
        label_text: str = "",
        sheen_boost: float = 0.0,
    ) -> None:
        """Draw the vinyl record, rotating a cached pixmap for smooth spin."""
        if size < 16:
            return

        pix = self._get_record_pixmap(size, label_tint, label_text, sheen_boost)
        cx = x + size / 2
        cy = y + size / 2

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._vinyl_angle)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(QPointF(-size / 2.0, -size / 2.0), pix)
        painter.restore()

    def _get_record_pixmap(
        self,
        size: int,
        label_tint: QColor | None,
        label_text: str,
        sheen_boost: float,
    ) -> QPixmap:
        """Cache record renderings; only the sheen level changes frequently."""
        key = (
            size,
            label_tint.rgba()
            if (label_tint is not None and label_tint.isValid())
            else -1,
            label_text,
            int(round(sheen_boost * 6)),
        )
        cached = self._vinyl_pixmap_cache.get(key)
        if cached is not None:
            return cached
        pix = self._build_record_pixmap(size, label_tint, label_text, sheen_boost)
        if len(self._vinyl_pixmap_cache) > 6:
            self._vinyl_pixmap_cache.clear()
        self._vinyl_pixmap_cache[key] = pix
        return pix

    def _build_record_pixmap(
        self,
        size: int,
        label_tint: QColor | None,
        label_text: str,
        sheen_boost: float,
    ) -> QPixmap:
        """Render a modern, flat-styled vinyl record into a static pixmap."""
        record = QPixmap(size, size)
        record.fill(Qt.transparent)
        p = QPainter(record)
        p.setRenderHint(QPainter.Antialiasing)

        cx = size / 2
        cy = size / 2
        outer_r = size / 2 - 1

        # --- Black vinyl disc (modern cool grey) -----------------------------
        disc_grad = QRadialGradient(cx, cy, outer_r)
        disc_grad.setColorAt(0.0, QColor(38, 38, 42))
        disc_grad.setColorAt(0.7, QColor(20, 20, 24))
        disc_grad.setColorAt(0.92, QColor(28, 28, 32))
        disc_grad.setColorAt(1.0, QColor(12, 12, 14))
        p.setPen(Qt.NoPen)
        p.setBrush(disc_grad)
        p.drawEllipse(QPointF(cx, cy), outer_r, outer_r)

        # --- Fine grooves (very subtle, non-glowing) -------------------------
        # Shared with the hit test that decides where the stow drag may start.
        label_r = outer_r * VINYL_LABEL_RADIUS_RATIO
        groove_pen = QPen(QColor(255, 255, 255, 10))
        groove_pen.setWidth(1)
        p.setPen(groove_pen)
        p.setBrush(Qt.NoBrush)
        r = label_r + 2
        step = max(1.5, outer_r / 55)
        while r < outer_r - 2:
            p.drawEllipse(QPointF(cx, cy), r, r)
            r += step

        # --- A few darker "track gap" rings for depth -------------------------
        p.setPen(QPen(QColor(0, 0, 0, 30), 1.5))
        groove_span = (outer_r - 2) - (label_r + 2)
        for frac in (0.30, 0.58, 0.85):
            rr = label_r + 2 + groove_span * frac
            p.drawEllipse(QPointF(cx, cy), rr, rr)

        # --- Rotating groove sheen (sells the spin; brightens when scratched) -
        sheen_a = int(VINYL_SHEEN_ALPHA * (0.8 + 2.2 * sheen_boost))
        sheen = QConicalGradient(cx, cy, -30)
        sheen.setColorAt(0.00, QColor(255, 255, 255, sheen_a))
        sheen.setColorAt(0.12, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.45, QColor(255, 255, 255, int(sheen_a * 0.5)))
        sheen.setColorAt(0.58, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.93, QColor(255, 255, 255, int(sheen_a * 0.7)))
        sheen.setColorAt(1.00, QColor(255, 255, 255, sheen_a))
        annulus = QPainterPath()
        annulus.addEllipse(QPointF(cx, cy), outer_r - 1.5, outer_r - 1.5)
        annulus.addEllipse(QPointF(cx, cy), label_r + 2, label_r + 2)
        p.setPen(Qt.NoPen)
        p.setBrush(sheen)
        p.drawPath(annulus)

        # --- Outer rim highlight (soft, flat) --------------------------------
        rim_pen = QPen(QColor(255, 255, 255, 18))
        rim_pen.setWidth(1)
        p.setPen(rim_pen)
        p.drawEllipse(QPointF(cx, cy), outer_r - 0.5, outer_r - 0.5)
        inner_rim_pen = QPen(QColor(0, 0, 0, 30))
        inner_rim_pen.setWidth(1)
        p.setPen(inner_rim_pen)
        p.drawEllipse(QPointF(cx, cy), label_r + 1, label_r + 1)

        # --- Central label (flat paper with optional cover tint) -------------
        label_grad = QRadialGradient(cx, cy, label_r)
        inner = QColor(250, 248, 244)
        mid = QColor(228, 225, 218)
        outer = QColor(200, 196, 188)
        if label_tint is not None and label_tint.isValid():
            inner = _blend_color(inner, label_tint, VINYL_LABEL_TINT_BLEND)
            mid = _blend_color(mid, label_tint, VINYL_LABEL_TINT_BLEND * 0.6)
            outer = _blend_color(outer, label_tint, VINYL_LABEL_TINT_BLEND * 0.4)
        label_grad.setColorAt(0.0, inner)
        label_grad.setColorAt(0.85, mid)
        label_grad.setColorAt(1.0, outer)
        p.setBrush(label_grad)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), label_r, label_r)

        # --- Spindle hole -----------------------------------------------------
        spindle_r = max(1.5, outer_r * 0.014)
        p.setBrush(QColor(16, 16, 18))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), spindle_r, spindle_r)

        # --- Tiny ring text around the label ----------------------------------
        if label_text:
            text = self._shorten_for_vinyl_label(label_text, max_chars=10)
            if text:
                font = ui_font(
                    max(7, int(size * VINYL_LABEL_RING_TEXT_SIZE_RATIO))
                )
                font.setWeight(QFont.Bold)
                font.setHintingPreference(QFont.PreferNoHinting)
                p.setFont(font)
                p.setPen(QColor(45, 45, 45, 240))
                ring_r = label_r - size * 0.035
                fm = QFontMetrics(font)

                # Compute per-character angular width so CJK chars get more room.
                spacing_rad = math.radians(1.8)
                char_angles = []
                for ch in text:
                    advance = fm.horizontalAdvance(ch)
                    char_angles.append(advance / ring_r)

                total_angle = sum(char_angles) + spacing_rad * max(0, len(text) - 1)
                # Cap at ~200° so it doesn't wrap around the back.
                if math.degrees(total_angle) > 200:
                    keep = 0
                    kept_angle = 0
                    limit = math.radians(200)
                    for i, a in enumerate(char_angles):
                        next_angle = kept_angle + a + (spacing_rad if i > 0 else 0)
                        if next_angle > limit:
                            break
                        keep += 1
                        kept_angle = next_angle
                    text = text[:keep]
                    char_angles = char_angles[:keep]
                    total_angle = kept_angle

                start_angle = -math.pi / 2 - total_angle / 2
                current_angle = start_angle
                for i, ch in enumerate(text):
                    angle = current_angle + char_angles[i] / 2
                    tx = cx + math.cos(angle) * ring_r
                    ty = cy + math.sin(angle) * ring_r
                    p.save()
                    p.translate(tx, ty)
                    # Rotate so the character stands upright relative to the ring.
                    p.rotate(math.degrees(angle) + 90)
                    char_rect = fm.boundingRect(ch)
                    # Use floating-point origin for smoother rotation.
                    p.drawText(
                        QPointF(-char_rect.width() / 2.0, char_rect.height() / 4.0),
                        ch,
                    )
                    p.restore()
                    current_angle += char_angles[i] + spacing_rad

        p.end()
        return record


    def _draw_rounded_cover(self, painter: QPainter, x: int, y: int, size: int) -> None:
        """Legacy square cover; kept for snapshots/debug if needed."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, size, size), 16, 16)
        painter.setClipPath(path)
        scaled = self._cover.scaled(
            size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        painter.drawPixmap(x, y, scaled)
        painter.setClipping(False)

        # Soft border.
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(x, y, size, size), 16, 16)

    # ------------------------------------------------------------------
    # Vinyl helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _shorten_for_vinyl_label(text: str, max_chars: int = 5) -> str:
        """Return a compact label string for the vinyl center."""
        text = text.strip()
        if not text:
            return ""
        # Take the first segment before common separators.
        for sep in (" - ", " — ", "–", "-", "_", "·", "/"):
            if sep in text:
                text = text.split(sep)[0]
                break
        text = text.strip()
        if len(text) > max_chars:
            return text[:max_chars].strip() + "…"
        return text

    def _update_vinyl_label_color(self) -> None:
        """Cache a dominant-color tint from the current cover."""
        if self._cover and not self._cover.isNull():
            self._vinyl_label_color = ColorExtractor.extract_dominant_color(
                self._cover, sample_size=64
            )
        else:
            self._vinyl_label_color = None

    def _current_audio_ms(self) -> float:
        """Where the audio is right now, whichever backend is driving it."""
        if self._audio_backend == "pcm" and self._engine is not None:
            return float(self._engine.position_ms())
        if self._player is not None:
            return float(self._player.position())
        return 0.0

    def _desired_scratch_position_raw(self) -> float:
        """Audio ms matching the hand's rotation during the current grab.

        `_scratch_base_ms` is the playhead captured when this grab began, so the
        target always starts out equal to where the audio already is and then
        follows the hand. Anchoring it on a position from an EARLIER grab is what
        made the track jump back after a scratch.
        """
        return self._scratch_base_ms + self._scratch_rotation_deg * VINYL_MS_PER_DEG

    def _desired_scratch_position(self) -> int:
        """Clamped scratch position for backends that must stay in range."""
        return int(
            max(0, min(self._duration, self._desired_scratch_position_raw()))
        )

    def _scratch_rate_from_velocity(self, velocity: float) -> float:
        """Convert angular velocity (deg/ms) to a playback rate.

        Uses a tanh curve so slow drags stay near 1x and fast flicks saturate
        smoothly toward the configured min/max limits.
        """
        rate = 1.0 + math.tanh(velocity * VINYL_SCRATCH_SENSITIVITY * 16.0) * 1.2
        return max(VINYL_RATE_MIN, min(VINYL_RATE_MAX, rate))

    def _return_rate_to_normal(self, dt_ms: float) -> None:
        """Frame-rate independently ease playback rate back to 1x."""
        if self._player is None:
            return
        current = self._player.playbackRate()
        if abs(current - 1.0) <= 0.005:
            return
        factor = 1.0 - math.exp(-dt_ms / VINYL_RATE_RETURN_TAU_MS)
        self._player.setPlaybackRate(current + (1.0 - current) * factor)

    def _begin_scratch(self) -> None:
        """Hand the platter over to the pointer: audio follows the hand."""
        if not self._vinyl_scratch_armed:
            return
        self._vinyl_scratch_armed = False
        self._vinyl_scratch_engaged = True
        # The angle baseline AND the audio baseline must belong to the same
        # instant. Both are captured at PRESS: the grab is armed on press but
        # engaged on the first move, so anchoring the angle at press while
        # sampling the audio position on the first move would make the first
        # move's rotation count against an audio position taken later -- which
        # threw the playhead forward by however far the pointer had travelled.
        centre = self._vinyl_record_center
        anchor = self._vinyl_press_pos or self._mouse
        angle = math.atan2(anchor.y() - centre.y(), anchor.x() - centre.x())
        self._vinyl_scratch_start_angle = angle
        self._vinyl_last_mouse_angle = angle
        self._vinyl_angular_velocity = 0.0
        self._vinyl_scratch_delta = 0.0
        self._vinyl_drag_timer.restart()
        # Re-anchor the unwrapped rotation onto the audio, so the playhead
        # derived from it equals where the track already is. `_vinyl_angle` is
        # the same quantity reduced to 0-360 purely for display.
        audio_ms = self._vinyl_press_audio_ms
        self._scratch_base_ms = audio_ms
        self._scratch_rotation_deg = 0.0
        # Put the displayed rotation where the audio is, so the record does not
        # visibly snap when the grab begins.
        self._vinyl_angle = (audio_ms / VINYL_MS_PER_DEG) % 360.0
        self._angle_offset_ms = 0.0
        if self._audio_backend == "pcm" and self._engine is not None:
            self._engine.set_scratching(True)
            self._start_playback()
        elif self._player is not None:
            self._player.play()
        self._update_cursor()

    def _stow_vinyl(self) -> None:
        """Throw the record back into its sleeve with a flick-and-settle."""
        if not self._vinyl_out:
            return
        # Drop the grab as well as any engaged scratch: this path can be
        # reached with the scratch merely armed and never started.
        self._vinyl_scratch_armed = False
        self._vinyl_scratch_engaged = False
        if self._vinyl_dragging:
            self._vinyl_dragging = False
            self._end_scratch()
        self._vinyl_out = False
        self._vinyl_out_anim.stop()
        self._vinyl_out_anim.setStartValue(self._vinyl_out_progress)
        self._vinyl_out_anim.setEndValue(0.0)
        # OutCubic reads as a toss that decelerates into the sleeve, rather
        # than the pull-with-overshoot used when sliding it out.
        self._vinyl_out_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._vinyl_out_anim.start()

    def _end_scratch(self) -> None:
        """Release the scratch: spin down from hand speed back to normal."""
        self._vinyl_scratch_armed = False
        if not self._vinyl_dragging:
            return
        self._vinyl_scratch_engaged = False
        # The scratch mapping only holds while dragging. Settle the record onto
        # the playhead the audio actually ended on -- including any full turns,
        # which the display angle cannot represent -- so nothing points back at
        # an older scratch once the hand lets go.
        landed = self._current_audio_ms()
        self._vinyl_scratch_start_position = landed
        self._vinyl_press_audio_ms = landed
        self._scratch_base_ms = landed
        self._scratch_rotation_deg = 0.0
        self._vinyl_angle = (landed / VINYL_MS_PER_DEG) % 360.0
        self._angle_offset_ms = 0.0
        self._vinyl_scratch_delta = 0.0
        if (
            self._audio_backend == "pcm"
            and self._engine is not None
            and self._duration > 0
        ):
            # Release speed in 1x units; a backwards release brakes through
            # zero and spins back up, like a real platter.
            speed = self._vinyl_angular_velocity / VINYL_SPIN_DEG_PER_MS
            speed = max(
                -VINYL_RELEASE_SPEED_CLAMP,
                min(VINYL_RELEASE_SPEED_CLAMP, speed),
            )
            self._engine.release(speed, VINYL_RELEASE_TAU_MS / 1000.0)
        elif self._player is not None and self._duration > 0:
            desired_ms = self._desired_scratch_position()
            speed = 1.0 + self._vinyl_angular_velocity * 16.0 / 15.0
            self._player.setPlaybackRate(
                max(VINYL_RELEASE_RATE_MIN, min(VINYL_RELEASE_RATE_MAX, speed))
            )
            if abs(self._player.position() - desired_ms) > 50:
                self._player.setPosition(desired_ms)
        self._vinyl_dragging = False
        self._update_cursor()
        self.update()

    def _on_vinyl_label(self, pos: QPoint) -> bool:
        """Whether `pos` is inside the record's centre label, not the black disc.

        The label is the paper circle in the middle (drawn at 34% of the disc
        radius). It is the only place the throw-back gesture may start: pressing
        the outer black area always means scratching, so dragging right from
        there cannot be confused with stowing the record.
        """
        radius = self._vinyl_record_radius
        if radius <= 0:
            return False
        centre = self._vinyl_record_center
        dx = pos.x() - centre.x()
        dy = pos.y() - centre.y()
        label_r = radius * VINYL_LABEL_RADIUS_RATIO
        return dx * dx + dy * dy <= label_r * label_r

    def _vinyl_travel_px(self) -> float:
        """Horizontal distance the record covers between stowed and pulled out.

        Mirrors the geometry in _draw_cover_and_vinyl, so a hand-driven drag can
        be mapped onto vinylOutProgress one-to-one.
        """
        size = self._sleeve_rect.width()
        if size <= 0:
            return 1.0
        record_size = int(size * 0.84)
        record_r = record_size / 2 - 1
        peek = record_size * VINYL_PEEK_FRACTION
        in_dx = size / 2 - record_r + peek
        return max(1.0, float(in_dx))

    def _vinyl_peek_rect(self) -> QRect:
        """The sliver of record showing past the sleeve's right edge.

        Only this region accepts a click while the record is stowed, so the
        sleeve itself stays inert.
        """
        sleeve = self._sleeve_rect
        centre = self._vinyl_record_center
        radius = self._vinyl_record_radius
        if not sleeve.isValid() or radius <= 0:
            return QRect()
        left = max(int(round(centre.x() - radius)), sleeve.right() + 1)
        right = min(int(round(centre.x() + radius)), sleeve.right() + 1 + 2 * int(radius))
        top = int(round(centre.y() - radius))
        bottom = int(round(centre.y() + radius))
        if right <= left:
            return QRect()
        return QRect(left, top, right - left, bottom - top)

    def _draw_track_info(self, painter: QPainter, x: int, y: int, w: int) -> None:
        """Draw title / artist + album / tech specs under the album cover.

        Any line too long for the column scrolls horizontally instead of being
        clipped: it rests, slides to reveal the tail, rests again, then snaps
        back. Short lines never move.
        """
        if not self._track_info:
            return

        # Line 1: Song title.
        title = self._song_title or "未知标题"
        title_font = ui_font(14)
        title_font.setWeight(HEADING_WEIGHT)
        self._draw_info_line(
            painter, "title", title, title_font, QColor(255, 255, 255),
            x, y, w, 24,
        )
        y += 26

        # Line 2: Artist · Album.
        meta_parts: list[str] = []
        if self._song_artist and self._song_artist != "未知艺术家":
            meta_parts.append(self._song_artist)
        if self._album:
            meta_parts.append(self._album)
        meta_line = " · ".join(meta_parts)
        if meta_line:
            meta_font = ui_font(11)
            meta_font.setWeight(HEADING_WEIGHT)
            self._draw_info_line(
                painter, "meta", meta_line, meta_font, QColor(255, 255, 255, 170),
                x, y, w, 20,
            )
        y += 22

        # Line 3: Source container  Format  SampleRate  BitDepth  Bitrate.
        # The source comes first so an unpacked ncm reads as "NCM · FLAC ..."
        # rather than claiming the file on disk is a flac.
        tech_parts: list[str] = []
        if self._source_label:
            tech_parts.append(self._source_label)
        fmt = self._track_info.get("format")
        if fmt:
            tech_parts.append(str(fmt))
        sr = self._track_info.get("sample_rate")
        if sr:
            tech_parts.append(f"{sr / 1000:.1f} kHz")
        bps = self._track_info.get("bits_per_sample")
        if bps:
            tech_parts.append(f"{bps} bit")
        br = self._track_info.get("bitrate")
        if br:
            tech_parts.append(f"{br // 1000} kbps")
        tech_line = "  ·  ".join(tech_parts)
        if tech_line:
            tech_font = ui_font(10)
            tech_font.setWeight(HEADING_WEIGHT)
            self._draw_info_line(
                painter, "tech", tech_line, tech_font, QColor(255, 255, 255, 140),
                x, y, w, 18,
            )

    def _info_scroll_state(self, key: str) -> dict:
        state = self._info_scroll.get(key)
        if state is None:
            state = {
                "text": "",
                "offset": 0.0,
                "span": 0.0,
                "fits": True,
                "gap": False,
                "pause": INFO_SCROLL_HEAD_PAUSE_MS,
            }
            self._info_scroll[key] = state
        return state

    def _sync_info_scroll(self, key: str, text: str, font, width: int) -> dict:
        """Refresh a line's marquee state for the current text and column width."""
        state = self._info_scroll_state(key)
        available = max(1, width)
        if state["text"] != text:
            # New track or new metadata: start over from the head.
            state["text"] = text
            state["offset"] = 0.0
            state["pause"] = INFO_SCROLL_HEAD_PAUSE_MS
            state["gap"] = False
        span = float(
            QFontMetrics(font).horizontalAdvance(text) - available
        )
        state["span"] = max(0.0, span)
        state["fits"] = state["span"] <= 1.0
        if state["fits"]:
            state["offset"] = 0.0
        return state

    def _update_info_scroll(self, dt_ms: float) -> None:
        """Advance every marquee by real elapsed time (frame-rate independent)."""
        for state in self._info_scroll.values():
            if state["fits"] or state["span"] <= 0:
                continue
            if state["pause"] > 0:
                state["pause"] = max(0.0, state["pause"] - dt_ms)
                continue
            state["offset"] += INFO_SCROLL_SPEED_PX_S * (dt_ms / 1000.0)
            if state["offset"] >= state["span"]:
                if not state["gap"]:
                    # Reached the tail: hold so the end can be read, then loop.
                    state["gap"] = True
                    state["pause"] = INFO_SCROLL_TAIL_PAUSE_MS
                elif state["pause"] <= 0:
                    state["offset"] = 0.0
                    state["gap"] = False
                    state["pause"] = INFO_SCROLL_HEAD_PAUSE_MS
            elif state["gap"]:
                state["gap"] = False

    def _draw_info_line(
        self, painter: QPainter, key: str, text: str, font, color: QColor,
        x: int, y: int, w: int, h: int,
    ) -> None:
        """Draw one info line, centred when it fits and marqueeing when it does not."""
        state = self._sync_info_scroll(key, text, font, w)
        painter.setFont(font)
        painter.setPen(color)

        if state["fits"]:
            painter.drawText(x, y, w, h, Qt.AlignCenter, text)
            return

        fm = QFontMetrics(font)
        baseline = y + (h + fm.ascent() - fm.descent()) // 2
        painter.save()
        # Clip to the column so the text can never spill over the cover or the
        # neighbouring panel.
        painter.setClipRect(x, y, w, h)
        painter.drawText(
            int(x - state["offset"]),
            int(baseline),
            text,
        )
        painter.restore()

    def _draw_progress_bar(
        self, painter: QPainter, x: int, y: int, w: int, h: int,
        slider: ElasticSlider,
    ) -> None:
        value = slider.visual

        # Hover/drag growth is spring-driven (see ElasticSlider.update), so the
        # bar eases wider and back instead of snapping between two heights.
        expand = slider.expand
        bar_h = h * (1.0 + 0.8 * expand)
        bar_y = y + (h - bar_h) / 2.0

        radius = max(3.0, bar_h / 2.0)
        track = QColor(255, 255, 255, 30)
        fill = QColor(118, 185, 0)
        painter.setPen(Qt.NoPen)

        # The track stretches to contain the elastic fill; when the fill
        # overshoots an end, the border goes with it but the strong wall
        # physics keeps the overshoot small.
        fill_end = x + value * w
        track_left = min(x, fill_end)
        track_right = max(x + w, fill_end)
        track_w = max(0.0, track_right - track_left)
        painter.setBrush(track)
        painter.drawRoundedRect(
            QRectF(track_left, bar_y, track_w, bar_h), radius, radius
        )

        # Fill can overshoot the normal track ends for the bounce effect.
        fill_left = min(x, fill_end)
        fill_right = max(x, fill_end)
        fill_w = max(0.0, fill_right - fill_left)
        if fill_w > 0:
            painter.setBrush(fill)
            painter.drawRoundedRect(
                QRectF(fill_left, bar_y, fill_w, bar_h), radius, radius
            )

        # Handle fades in with the expansion so it doesn't pop into view.
        if expand > 0.02:
            handle_x = x + value * w
            handle_y = bar_y + bar_h / 2.0
            handle_r = bar_h / 2.0 + 1.0
            painter.setBrush(
                QColor(255, 255, 255, int(240 * min(1.0, expand)))
            )
            painter.drawEllipse(QPointF(handle_x, handle_y), handle_r, handle_r)

    def _press_button(self, kind: str) -> None:
        """Press a button down into the screen, as if poked with a fingertip.

        The force goes downward/inward rather than sideways: the glyph is pushed
        down and squashed vertically, then springs back with a couple of soft
        wobbles, like pressing into a piece of jelly.
        """
        state = self._btn_press.setdefault(
            kind, {"offset": 0.0, "velocity": 0.0, "squash": 0.0}
        )
        state["velocity"] += BTN_PRESS_KICK

    def _update_button_press(self, dt_ms: float) -> None:
        """Spring every pressed button back up to rest, wobbling as it goes."""
        if not self._btn_press:
            return
        # Scale the integrator by real elapsed time so the wobble is the same
        # at any frame rate.
        scale = max(0.2, min(3.0, dt_ms / 16.0))
        for state in self._btn_press.values():
            stiffness = BTN_PRESS_STIFFNESS * scale
            damping = BTN_PRESS_DAMPING * scale
            state["velocity"] += (
                -state["offset"] * stiffness - state["velocity"] * damping
            )
            state["offset"] += state["velocity"] * scale
            # Squash trails the offset, which reads as the shape lagging behind
            # the motion instead of moving rigidly with it. Normalised against
            # the kick so it stays a small deformation rather than scaling with
            # however far the button happens to travel.
            target_squash = state["offset"] / max(1.0, BTN_PRESS_KICK)
            state["squash"] += (target_squash - state["squash"]) * min(
                1.0, 0.25 * scale
            )
            if (
                abs(state["offset"]) < 0.02
                and abs(state["velocity"]) < 0.02
            ):
                state["offset"] = 0.0
                state["velocity"] = 0.0
                state["squash"] = 0.0

    def _draw_volume_bar(
        self, painter: QPainter, x: int, y: int, w: int, h: int,
        slider: ElasticSlider, icon_offsets: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        icon_w = 20
        gap = 10
        bar_x = x + icon_w + gap
        bar_w = w - (icon_w + gap) * 2
        offset_l, offset_r = icon_offsets

        # The offsets move the icons sideways, not up and down: the slider's
        # wall impact shoves them along the bar's axis, so the wobble reads as
        # the volume bar pushing them rather than as a vertical bounce.
        self._draw_speaker_icon(
            painter, QRect(x + int(offset_l), int(y - 7), icon_w, 20), muted=True
        )
        self._draw_speaker_icon(
            painter,
            QRect(bar_x + bar_w + gap + int(offset_r), int(y - 7), icon_w, 20),
            muted=False,
        )
        self._draw_progress_bar(painter, bar_x, y, bar_w, h, slider)

    def _update_volume_icon_physics(self) -> None:
        """Push the speaker icons outward, then wobble them back home.

        Two sources drive this:

        * While the pointer holds the fill against an end, a steady outward
          force is applied. This is the case that actually matters for a slow
          drag -- the spring only overshoots the wall in proportion to its
          speed, so a slow drag barely penetrates and an impact-only trigger
          would never fire.
        * A genuine impact (the fill overshooting the soft wall) adds a
          one-shot kick on top, which is what makes a jump to the end snap.

        The return spring is deliberately underdamped so each icon drifts back
        with a few wobbles, like a magnet pulling it home.
        """
        stiffness = 0.16
        damping = 0.24

        # Sustained push while the fill is held at an end. `wall_side` is only
        # set on penetration, so derive the side from the fill position here.
        held_side = 0
        if self._volume_slider.dragging:
            if self._volume_slider.target >= 0.999:
                held_side = 1
            elif self._volume_slider.target <= 0.001:
                held_side = -1

        impact = self._volume_slider.wall_impact
        wall_side = self._volume_slider.wall_side

        push_l = 0.0
        push_r = 0.0
        if held_side == 1:
            push_r = VOLUME_ICON_PUSH_PX
        elif held_side == -1:
            push_l = VOLUME_ICON_PUSH_PX
        if wall_side == -1:
            push_l = max(push_l, impact * VOLUME_ICON_WALL_KICK)
        elif wall_side == 1:
            push_r = max(push_r, impact * VOLUME_ICON_WALL_KICK)

        # Sign check, since this is easy to get backwards: the icons are drawn
        # at `x + offset`, so a POSITIVE offset moves the right-hand speaker
        # outward (away from the bar) and the left-hand one inward. The fill
        # slamming into the RIGHT end must therefore push the right icon with a
        # positive force, and the LEFT end must push the left icon negatively.
        self._vol_icon_l_vel += (
            -self._vol_icon_l_offset * stiffness - self._vol_icon_l_vel * damping
            - push_l
        )
        self._vol_icon_l_offset += self._vol_icon_l_vel

        self._vol_icon_r_vel += (
            -self._vol_icon_r_offset * stiffness - self._vol_icon_r_vel * damping
            + push_r
        )
        self._vol_icon_r_offset += self._vol_icon_r_vel

        # Keep the shove modest: the icon sits beside the bar, not on a leash.
        limit = VOLUME_ICON_MAX_OFFSET
        self._vol_icon_l_offset = max(-limit, min(limit, self._vol_icon_l_offset))
        self._vol_icon_r_offset = max(-limit, min(limit, self._vol_icon_r_offset))

    @staticmethod
    def _rounded_triangle(
        tip: QPointF, base_a: QPointF, base_b: QPointF, radius: float
    ) -> QPainterPath:
        """A triangle with its three corners rounded off.

        QPainter can only round rectangles, so the icon shapes are built as
        paths: each corner is cut back and bridged with a quadratic curve. The
        cut-back distance is the SAME at every corner by construction -- an
        inset proportional to each corner's own edges instead leaves the sharp
        tip barely rounded while the base corners are cut deeply, which shifts
        the shape's vertical centre and makes the glyph look tilted.
        """
        points = [tip, base_a, base_b]

        def cut_back(source: QPointF, target: QPointF) -> QPointF:
            """Step `radius` from source toward target, never past the midpoint."""
            dx = target.x() - source.x()
            dy = target.y() - source.y()
            length = math.hypot(dx, dy)
            if length <= 0.0001:
                return QPointF(source)
            step = min(radius, length * 0.5)
            return QPointF(
                source.x() + dx / length * step,
                source.y() + dy / length * step,
            )

        path = QPainterPath()
        for i in range(3):
            prev_pt = points[(i - 1) % 3]
            cur = points[i]
            nxt = points[(i + 1) % 3]
            enter = cut_back(cur, prev_pt)
            leave = cut_back(cur, nxt)
            if i == 0:
                path.moveTo(enter)
            else:
                path.lineTo(enter)
            path.quadTo(cur, leave)
        path.closeSubpath()
        return path

    def _draw_button(self, painter: QPainter, rect: QRect, kind: str) -> None:
        # Press feedback: the whole button squeezes in toward its own centre and
        # then springs back out, as if a fingertip pressed into the middle of a
        # piece of jelly. Uniform scale, so the squeeze is symmetric.
        state = self._btn_press.get(kind)
        # Clamp the deformation: the jelly is a soft squeeze, never a mangled icon.
        squash = max(-1.0, min(1.0, state["squash"])) if state else 0.0

        radius = rect.width() / 2.0
        r = rect.width() * 0.22
        cx = rect.center().x()
        cy = rect.center().y()
        # >1 on the recoil so the button swells slightly past its rest size.
        button_scale = 1.0 - 0.13 * squash
        icon_scale = 1.0 - 0.18 * squash

        # Subtle circle background for all control buttons.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20 + int(14 * abs(squash))))
        painter.drawEllipse(QPointF(cx, cy), radius * button_scale,
                            radius * button_scale)

        # Draw the glyph scaled about the button centre: local coordinates are
        # offsets from that centre, so one transform covers every icon shape.
        painter.save()
        painter.translate(cx, cy)
        painter.scale(icon_scale, icon_scale)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 230))

        if kind == "play":
            painter.drawPath(self._rounded_triangle(
                QPointF(r * 0.95, 0),
                QPointF(-r * 0.5, -r),
                QPointF(-r * 0.5, r),
                r * 0.42,
            ))
        elif kind == "pause":
            bar_w = max(2, int(r * 0.35))
            gap = max(2, int(r * 0.4))
            painter.drawRoundedRect(
                QRectF(-gap - bar_w, -r, bar_w, r * 2), bar_w / 2, bar_w / 2
            )
            painter.drawRoundedRect(
                QRectF(gap, -r, bar_w, r * 2), bar_w / 2, bar_w / 2
            )
        elif kind == "previous":
            # A single rounded triangle pointing left, no bar.
            painter.drawPath(self._rounded_triangle(
                QPointF(-r * 1.05, 0),
                QPointF(r * 0.55, -r),
                QPointF(r * 0.55, r),
                r * 0.42,
            ))
        elif kind == "next":
            # A single rounded triangle pointing right, no bar.
            painter.drawPath(self._rounded_triangle(
                QPointF(r * 1.05, 0),
                QPointF(-r * 0.55, -r),
                QPointF(-r * 0.55, r),
                r * 0.42,
            ))
        elif kind == "folder":
            painter.drawPath(self._folder_path(r))
        elif kind == "menu":
            # Hamburger: fully rounded pill ends, matching the pause bars.
            # Sized in whole-pixel steps: at a 36 px button, nudging these by a
            # few hundredths of `r` rounds away and the glyph does not change.
            bar_w = r * 1.90
            bar_h = r * 0.26
            gap = r * 0.62
            for offset in (-gap, 0, gap):
                painter.drawRoundedRect(
                    QRectF(-bar_w / 2, offset - bar_h / 2, bar_w, bar_h),
                    bar_h / 2, bar_h / 2,
                )

        painter.restore()

    @staticmethod
    def _folder_path(r: float) -> QPainterPath:
        """A folder outline with one continuous, smooth silhouette.

        Drawn the classic way: the tab sits FLUSH with the body's top edge and
        the body's top-right shoulder falls away from the tab in one straight
        chamfer. An earlier attempt put the tab on its own raised step reached by
        a quadratic dip, which read as a tab stuck onto a block with a notch
        beside it -- the silhouette must never dip below the body's top edge.
        Built in the button's centre-origin coordinates.
        """
        half_w = r * 0.88
        half_h = r * 0.58
        radius = r * 0.22          # bottom corner rounding
        tab_h = r * 0.24           # how far the tab rises above the body's top
        tab_w = r * 0.76           # how far the tab reaches right
        # The chamfer must be SHORT and STEEP. A long shallow one swallows the
        # tab and the icon reads as a body with its top-right corner cut off,
        # rather than as a tab standing up on the left.
        chamfer = r * 0.26

        left, right = -half_w, half_w
        top, bottom = -half_h, half_h
        # The tab rises above the body, so the silhouette's vertical centre sits
        # that much higher than the body's; shift everything down by half of it
        # to keep the glyph optically centred in the button.
        top += tab_h / 2.0
        bottom += tab_h / 2.0
        tab_top = top - tab_h
        tab_right = left + tab_w
        chamfer_end = tab_right + chamfer

        path = QPainterPath()
        # Rise out of the left edge into the tab's top-left corner.
        path.moveTo(left, tab_top + tab_h * 0.45)
        path.quadTo(left, tab_top, left + tab_h * 0.45, tab_top)
        path.lineTo(tab_right, tab_top)
        # Short, steep drop from the tab down to the body's top edge.
        path.lineTo(chamfer_end, top)
        path.lineTo(right - radius, top)
        path.quadTo(right, top, right, top + radius)
        path.lineTo(right, bottom - radius)
        path.quadTo(right, bottom, right - radius, bottom)
        path.lineTo(left + radius, bottom)
        path.quadTo(left, bottom, left, bottom - radius)
        path.lineTo(left, tab_top + tab_h * 0.45)
        path.closeSubpath()
        return path

    def _draw_speaker_icon(
        self, painter: QPainter, rect: QRect, muted: bool
    ) -> None:
        cx = rect.center().x()
        cy = rect.center().y()
        r = min(rect.width(), rect.height()) * 0.35

        # Speaker cone (filled, no outline to avoid ghosting).
        cone = QPolygonF([
            QPointF(cx - r * 0.7, cy - r * 0.5),
            QPointF(cx - r * 0.2, cy - r * 0.5),
            QPointF(cx + r * 0.5, cy - r),
            QPointF(cx + r * 0.5, cy + r),
            QPointF(cx - r * 0.2, cy + r * 0.5),
            QPointF(cx - r * 0.7, cy + r * 0.5),
        ])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.drawPolygon(cone)

        if muted:
            # Draw a small cross, spaced a bit further from the cone.
            pen = QPen(QColor(255, 255, 255, 220))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            x1 = cx + r * 0.85
            y1 = cy - r * 0.55
            x2 = cx + r * 1.25
            y2 = cy + r * 0.55
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            painter.drawLine(int(x2), int(y1), int(x1), int(y2))
        else:
            # Draw two sound-wave arcs, spaced further out from the cone.
            pen = QPen(QColor(255, 255, 255, 220))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            arcs = [
                (cx + r * 0.7, cy - r * 0.55, r * 0.7, r * 1.1),
                (cx + r * 1.05, cy - r * 0.85, r * 1.15, r * 1.7),
            ]
            for ax, ay, aw, ah in arcs:
                painter.drawArc(
                    int(ax),
                    int(ay),
                    int(aw),
                    int(ah),
                    -30 * 16,
                    60 * 16,
                )

    def _blurred_layer(self, image: QImage, key: tuple) -> QImage:
        """A blurred copy of *image*, memoised on *key*.

        Shrink and grow: Qt cannot blur a pixmap directly, and at these sizes the interpolation
        does the job convincingly. The cache matters because the layer is only rebuilt when its
        key changes -- during playback the scroll moves every frame, so the key includes it.
        """
        cached = _LYRICS_BLUR_CACHE.get("key")
        if cached == key and _LYRICS_BLUR_CACHE.get("image") is not None:
            return _LYRICS_BLUR_CACHE["image"]

        small = image.scaled(
            max(1, int(image.width() / LYRICS_BLUR_SHRINK)),
            max(1, int(image.height() / LYRICS_BLUR_SHRINK)),
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
        )
        blurred = small.scaled(image.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        _LYRICS_BLUR_CACHE["key"] = key
        _LYRICS_BLUR_CACHE["image"] = blurred
        return blurred

    def _draw_lyrics(self, painter: QPainter, rect: QRect) -> None:
        if not self._lyrics:
            return

        self._lyrics_panel_rect = rect
        self._lyrics_hit_rects = []

        # Keep lyrics away from the panel edges.
        h_margin = 30
        _idle, _active, margin = self._lyrics_size_spec()
        v_margin = margin
        fade_zone = 70
        x = rect.left() + h_margin
        base_y = rect.top() + 50
        y = base_y - self._lyrics_scroll_offset
        max_w = max(20, rect.width() - h_margin * 2)
        visible_top = rect.top() + v_margin
        visible_bottom = rect.bottom() - v_margin
        text_flags = Qt.TextWordWrap | self._lyrics_align_flag()

        has_timing = any(t >= 0 for t, _ in self._lyrics)
        active = self._current_lyric_index() if has_timing else -1

        # Whether the other lines recede, decided once for the whole panel.
        #
        # Pointing at a line that is not the one being sung lifts the fade entirely, so the panel
        # reads as if the setting were switched off. Pointing at the active line changes nothing --
        # it is already at full strength, and there is nothing to release.
        #
        # One decision for all lines rather than an exception per line: the earlier per-line version
        # had to keep the hovered line out of the blurred layer, put it back sharp, and work out where
        # it went, and each of those steps was a chance to draw it twice or in the wrong place.
        # Where the active line sits, captured during the layer pass. That pass walks the whole
        # layout even for the lines it leaves out -- the cursor advances by the measured height either
        # way -- so it is the one place the position is known. It used to be recorded implicitly, as a
        # side effect of the line being drawn into the layer; once it stopped being drawn there, the
        # sharp pass had nothing to look up and silently drew nothing at all.
        active_rect = None
        active_draw_y = None

        # Everything below is a closure over `target` so the same code can draw to the widget or
        # to an offscreen layer, depending on whether the lines are being blurred.
        def draw_lines(target: QPainter, skip=(), only: int = -1) -> None:
            """Draw the visible lines onto *target*.

            A closure over the geometry computed above so the same code can serve the widget's
            painter or the offscreen layer used for the blur, rather than duplicating the layout.

            `skip` leaves lines out -- the layer uses it to exclude the ones that will be drawn
            sharp on top, because cutting them back out with a clip leaves a visible hard edge around
            them once the blur is strong. `only` draws a single line, which is how those are put back.
            """
            nonlocal y, active_rect, active_draw_y
            # `skip` is a collection of indices, not one index. It was declared as a single int and
            # then handed a list, and `i == skip` was False for every line as a result -- the layer
            # drew everything, including the line it was supposed to leave out, and that line came
            # down a second time in a slightly different place. An int is still accepted here so a
            # single-index call cannot fail the same silent way.
            skipped = {skip} if isinstance(skip, int) else set(skip)
            # Reset on entry: the caller may run this more than once per paint (the blur path
            # draws the layer, then the active line again on top), and a cursor left at the end
            # of the list would draw nothing the second time.
            y = base_y - self._lyrics_scroll_offset
            for i, (t, line) in enumerate(self._lyrics):
                if y > rect.bottom():
                    break

                # Two filters, and "only" wins: a call that names one line draws that line and
                # nothing else. Combining them with `or` let `skip` take precedence, so the call
                # meant to redraw the active line skipped it a second time -- which is why it never
                # appeared under the colour visualiser, and why it was not clickable there either.
                if only >= 0:
                    if i != only:
                        y += self._lyric_entry_height(i, max_w) + LYRICS_ENTRY_GAP
                        continue
                    # Drawn at the position the layer pass gave this line, straight to the widget.
                    # Walking the layout again would land it a few pixels high: heights are measured
                    # with the tier's idle font while the active line is drawn with its animated one,
                    # which is taller, so the cursor advances less than the drawing did. Reusing the
                    # recorded rect also makes the painted line and its clickable area the same
                    # rectangle, which is what hover and click resolve against.
                    target.setPen(QColor(255, 255, 255, 255))
                    if i == active and active_draw_y is not None:
                        draw_y = active_draw_y
                    elif i == active and active_rect is not None:
                        draw_y = float(active_rect.top())
                    else:
                        recorded = next((r for r, index in self._lyrics_hit_rects if index == i),
                                        None)
                        if recorded is None:
                            return
                        draw_y = float(recorded.top())
                    # Measured here rather than taken from the recorded rect: the rect carries the
                    # height the layout walk used, and for the active line that is the idle font's
                    # height, smaller than the text. The helper sets the font too, so the box and the
                    # glyphs come from the same one.
                    block_h = self._lyric_drawn_height(target, i, line, max_w, text_flags)
                    target.drawText(QRectF(x, draw_y, max_w, block_h), text_flags, line)
                    self._lyrics_hit_rects.append((QRect(x, int(draw_y), max_w, int(block_h)), i))
                    return
                if i in skipped:
                    # Measured with the font the drawing path will use rather than the tier's idle
                    # font: an active line is drawn larger than the rig assumes, and a box measured
                    # short squeezes the text into it.
                    block_h = self._lyric_drawn_height(target, i, line, max_w, text_flags)
                    if i == active:
                        # The fractional y, not the rounded one: the blurred path draws this line at
                        # the layout position, so the sharp path has to use the same number or the
                        # text sits a pixel lower the moment the blur is released. The rectangle
                        # keeps its own rounding, since it is compared against mouse positions.
                        active_draw_y = float(y)
                        active_rect = QRect(x, int(y), max_w, int(block_h))
                    y += block_h + LYRICS_ENTRY_GAP
                    continue

                is_active = i == active
                # Sets the font as well as measuring: the box and the text have to come from the same
                # font, or the text is fitted into a box that was sized for a different one.
                block_h = self._lyric_drawn_height(target, i, line, max_w, text_flags)

                # The line's own ripple, over the list's scroll. Held apart from `y` so the
                # layout walk stays on the rig -- folding it into `y` would shift every line
                # after this one by the same amount.
                draw_y = y + self._lyrics_line_offset(i)

                if y + block_h <= rect.top():
                    y += block_h + LYRICS_ENTRY_GAP
                    continue

                # Distance-based fade around the active line.
                dist = abs(i - active) if active >= 0 else 0
                if is_active:
                    base_alpha = 255
                elif not faded:
                    # Either the effect is off, or the pointer is releasing it. Both draw at the
                    # ordinary strength, and neither singles out the line under the pointer: the
                    # release is for the whole panel, so no line looks selected.
                    # The fade is not in effect -- another visualiser, or the setting switched off --
                    # so the ordinary strength is used outright. Blending here let the spring's
                    # resting position decide the panel's look even though nothing was being faded,
                    # and at rest that position is the faded end, so the faded alphas were computed
                    # for a panel that never showed them.
                    base_alpha = max(
                        LYRICS_IDLE_ALPHA_MIN,
                        LYRICS_IDLE_ALPHA - dist * LYRICS_IDLE_ALPHA_STEP,
                    )
                    if self._visualizer == _VISUALIZER_COLORS:
                        base_alpha = int(round(base_alpha * LYRICS_COLOR_IDLE_SCALE))
                else:
                    # Two strengths for a line that is not being sung, and the fade's spring moves
                    # between them: at 1 it is the faded look, at 0 the ordinary one. The transition
                    # animates in both directions, including when the pointer releases the effect.
                    faded_alpha = max(
                        LYRICS_FADE_ALPHA_MIN,
                        LYRICS_FADE_ALPHA - dist * LYRICS_FADE_ALPHA_STEP,
                    )
                    ordinary_alpha = max(
                        LYRICS_IDLE_ALPHA_MIN,
                        LYRICS_IDLE_ALPHA - dist * LYRICS_IDLE_ALPHA_STEP,
                    )
                    # 1 is fully faded and 0 is the ordinary look -- the value is at 1 when the
                    # panel is at rest, and at rest the effect is on.
                    blend = min(1.0, max(0.0, self._lyrics_fade_value))
                    base_alpha = int(round(ordinary_alpha + (faded_alpha - ordinary_alpha) * blend))

                # Edge fade so lyrics are not cut off hard against the top and bottom.
                center_y = draw_y + block_h / 2
                if center_y < visible_top:
                    edge_factor = max(0.0, 1.0 - (visible_top - center_y) / fade_zone)
                elif center_y > visible_bottom:
                    edge_factor = max(0.0, 1.0 - (center_y - visible_bottom) / fade_zone)
                else:
                    edge_factor = 1.0

                alpha = int(base_alpha * edge_factor)
                arrival = self._lyrics_arrival_alpha(i)
                if arrival < 1.0:
                    alpha = int(alpha * arrival)
                if alpha > 0:
                    # The just-copied line flashes: its glyphs brighten toward solid white.
                    # Nothing is painted behind them -- no block, no halo. A blurred halo was
                    # tried and removed: measured at dpr 2 it changed the frame by 0 pixels
                    # (the glyph brightening already dominates) while costing work and, before
                    # it was clipped, leaking a visible sliver of light outside the line's box.
                    if i == self._lyric_copy_flash_index and self._lyric_copy_flash > 0.0:
                        flash = self._lyric_copy_flash * edge_factor
                        alpha = int(alpha + (255 - alpha) * flash * LYRICS_COPY_FLASH_PEAK)
                    target.setPen(QColor(255, 255, 255, alpha))
                    # Drawn from a fractional y on purpose. Rounding to whole pixels makes the
                    # slow tail of a spring jump 0 or 2 px per frame instead of 1, which reads
                    # as stutter even though the frame rate is fine.
                    target.drawText(QRectF(x, draw_y, max_w, block_h), text_flags, line)
                    # The clickable area stays on whole pixels: it is compared against mouse
                    # positions, and a fractional rect there buys nothing.
                    self._lyrics_hit_rects.append((QRect(x, int(draw_y), max_w, block_h), i))

                y += block_h + LYRICS_ENTRY_GAP

        # By row, not by rectangle: the pointer only has to be level with a line, at any x. Tested per
        # rectangle it also had to be over the glyphs, so crossing a gap between two words -- or the
        # empty end of a short line -- dropped the hover and the fade came back mid-sweep.
        #
        # Taken here, after the walk, because the row test reads the rect list that this method clears
        # on entry and fills as it draws. Deciding it before the walk read an empty list and always
        # said no, while the tick -- reading the previous frame's list -- often said yes, and the two
        # overwrote each other every frame.
        # Judged against the rows the last completed frame recorded. The list being built below is
        # cleared on entry and filled in two passes, so it is empty or partial until the very end --
        # reading it here answered "nothing hovered" every time.
        self._lyrics_fade_lifted = self._lyrics_row_hovered(active)

        # Whether the panel is drawn through the blurred layer: the setting on, the colour visualiser,
        # and the pointer not releasing the effect. Dropping the blur is what makes the text sharp --
        # raising the alpha inside that layer only draws brighter blurred text.
        faded = (
            self._lyrics_fade
            and self._visualizer == _VISUALIZER_COLORS
            and not self._lyrics_fade_lifted
        )
        if not faded:
            draw_lines(painter)
            # Straight to the widget, but the rows are still the rows.
            self._lyrics_row_rects = list(self._lyrics_hit_rects)
            return

        # The lines drawn sharp rather than blurred. There is now only ever one: the line being sung.
        # It is drawn after the layer, so it must be left out of the layer -- an alpha of 255 buys
        # nothing inside a blurred copy, which softens whatever it is given. Drawing it in both places
        # is what produced a second, slightly offset copy of the words.
        sharp = [active] if active >= 0 else []

        # Colour visualiser: the panel is busy, so everything except the line being sung recedes
        # into it. The layer is only rebuilt when its inputs change.
        # Rasterised at PHYSICAL resolution, with no ratio of its own.
        #
        # The distinction matters and is easy to get wrong in either direction. Declaring a ratio on
        # a layer the size of the panel in logical pixels makes Qt rasterise the text at half the
        # resolution it is displayed at and then enlarge it, which shows up as grain -- the panel
        # looks like a magnified low-resolution image. Allocating at the device size and painting in
        # device pixels instead puts one image pixel behind each screen pixel.
        #
        # The painter is scaled so the drawing code can keep using logical units; the scale here is
        # the only one, so nothing is applied twice.
        ratio = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
        if ratio <= 0:
            ratio = 1.0
        layer = QImage(int(rect.width() * ratio), int(rect.height() * ratio),
                       QImage.Format_ARGB32_Premultiplied)
        layer.fill(Qt.transparent)
        layer_painter = QPainter(layer)
        try:
            layer_painter.setRenderHint(QPainter.Antialiasing)
            layer_painter.setRenderHint(QPainter.TextAntialiasing)
            layer_painter.scale(ratio, ratio)
            # The lines are drawn in widget coordinates, so the painter is moved to the panel's
            # origin as well -- without it the panel, which sits at x=600 in a 1200-wide window,
            # would have every line drawn outside a canvas only as wide as the panel.
            layer_painter.translate(-rect.left(), -rect.top())
            draw_lines(layer_painter, skip=sharp)
        finally:
            # Always closed. A QPainter left open aborts the process with no Python traceback,
            # so this must not depend on everything above it succeeding.
            layer_painter.end()

        if LYRICS_COLOR_OPACITY < 1.0:
            # Applied to the layer rather than per line: everything in it is non-active by
            # construction, so one pass over the whole thing is the same result for less code.
            #
            # Its own painter, without the translation above. Filling inside that translated system
            # would put the rectangle at the panel's offset instead of over the layer, so the
            # dimming would silently do nothing whenever the panel is not at the origin.
            dim = QPainter(layer)
            try:
                dim.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                dim.fillRect(layer.rect(), QColor(0, 0, 0, int(255 * LYRICS_COLOR_OPACITY)))
            finally:
                dim.end()

        key = (rect.width(), rect.height(), round(self._lyrics_scroll_offset, 2),
               active, self._lyrics_size, self._lyrics_align,
               round(self._lyric_copy_flash, 3), self._lyric_copy_flash_index,
               # Part of the layer's content: every line's alpha is blended by it, so a key without
               # it reuses the previous layer for the whole animation and the picture never moves.
               round(self._lyrics_fade_value, 3))
        blurred = self._blurred_layer(layer, key)

        # The layer never contained the active line, so it goes down whole. Then the active line is
        # drawn sharp on top -- and only it. Calling draw_lines for the whole list here would paint
        # every blurred line sharp again and undo the effect.
        # Drawn scaled down from device pixels to the panel's logical rectangle.
        painter.drawImage(QRectF(rect), blurred, QRectF(blurred.rect()))
        # No saving and restoring of the rect list: it was cleared at the top of this method and the
        # layer pass has recorded every line except the sharp ones, so drawing those completes it.
        # An earlier attempt saved a copy and restored it afterwards, which depended on what the list
        # happened to hold on entry and made hover and click resolve the wrong line.
        for index in sharp:
            draw_lines(painter, only=index)

        # The rows as drawn, kept for the hover test to read on the next frame. Both passes have run,
        # so the list is complete here and nowhere earlier.
        self._lyrics_row_rects = list(self._lyrics_hit_rects)

    def _refresh_lyrics_fade(self) -> None:
        """Recompute whether the pointer is releasing the fade.

        Called from the tick and from the draw. Both need it and they must not disagree: the spring
        travels towards what the tick decided, while the drawing blends by the same flag.

        The fade has to be in effect before there is anything to release, so the setting and the
        visualiser are part of the condition. Without them the spring moved on hover even with the
        effect switched off -- towards the faded end, which is the opposite of what the panel was
        showing, and it left the value parked where the drawing did not expect it.
        """
        in_effect = self._lyrics_fade and self._visualizer == _VISUALIZER_COLORS
        active = self._current_lyric_index() if any(t >= 0 for t, _ in self._lyrics) else -1
        self._lyrics_fade_lifted = in_effect and self._lyrics_row_hovered(active)

    def _lyrics_region_contains(self, x: float, y: float, active: int) -> bool:
        """Whether the pointer is over the lyrics that have not been sung yet.

        A rectangle, not a band: the height covers the lines still ahead -- from just above the one
        that comes next to just below the last on screen -- and the width covers the words, from just
        before where they start to just after the widest of them ends. Between the lines counts, and
        so does anything within a line's own width; off to either side of the words does not, which is
        what keeps the effect from triggering out over the artwork.

        With nothing still to come there is no region: there are no words left to point at.
        """
        upcoming = [(rect, index) for rect, index in self._lyrics_row_rects if index > active]
        if not upcoming:
            return False
        left = min(rect.left() for rect, _ in upcoming) - LYRICS_HOVER_PAD_PX
        top = min(rect.top() for rect, _ in upcoming) - LYRICS_HOVER_PAD_PX
        bottom = max(rect.bottom() for rect, _ in upcoming) + LYRICS_HOVER_PAD_PX
        # The widest line is what the column reaches to. Measuring per line and taking the maximum
        # keeps short lines from widening it, which is what using the column's own width would do.
        right = max(
            rect.left() + self._lyric_entry_width(index, rect.width())
            for rect, index in upcoming
        ) + LYRICS_HOVER_PAD_PX
        return left <= x <= right and top <= y <= bottom

    def _lyrics_index_near(self, y: float, active: int) -> int:
        """Some line still to come that the pointer is level with, for "is it over the region at all".

        Any of them will do -- the effect is panel-wide, and this only has to distinguish being over
        the region from being off it. The exact rectangles cannot answer that, because a point in a
        gap between two lines belongs to none of them.
        """
        for rect, index in self._lyrics_row_rects:
            if index > active and rect.top() <= y <= rect.bottom():
                return index
        return -1

    def _lyrics_row_hovered(self, active: int) -> bool:
        """Whether the pointer is over the lyrics other than the one being sung.

        No guard on the index beyond the pointer being on the lyrics at all: it is -2 when the pointer
        sits in a gap inside the region, which is deliberately part of the region. Rejecting negatives
        here threw those points away one line after the region had accepted them.
        """
        if self._lyrics_hover_index == -1:
            return False
        return self._lyrics_region_contains(self._mouse.x(), self._mouse.y(), active)

    def _lyric_index_at(self, pos: QPoint) -> int:
        """Index of the lyric line under *pos*, or -1.

        Uses the rects recorded by the last paint, so it matches exactly what is
        on screen right now (including wrapping and the scrolled position).
        """
        for rect, index in self._lyrics_hit_rects:
            if rect.contains(pos):
                return index
        return -1

    def _copy_lyric_at(self, pos: QPoint) -> bool:
        """Copy the lyric line under *pos* and flash it. False when there is none.

        Flashing the line itself is the whole confirmation: no toast, no dialog,
        nothing covering the words being copied.
        """
        index = self._lyric_index_at(pos)
        if index < 0 or index >= len(self._lyrics):
            return False
        text = self._lyrics[index][1]
        if not text:
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        self._lyric_copy_flash_index = index
        self._lyric_copy_flash = 1.0
        self.update()
        return True

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._mouse_down = True
        self._mouse = event.position()
        pos = event.position().toPoint()

        # Right-click copies the lyric under the cursor. Handled before the
        # left-button paths so a right click can never start a lyrics drag or a
        # seek, and it consumes the event so no context menu appears.
        if event.button() == Qt.RightButton and self._copy_lyric_at(pos):
            event.accept()
            return

        # Close popups when clicking outside them.
        if self._music_menu.isVisible() and not self._music_menu.geometry().contains(pos):
            self._hide_music_menu()
            return
        if self._playlist_panel.isVisible() and not self._playlist_panel.geometry().contains(pos):
            self._hide_playlist_panel()
            return
        if (
            self._visualizer_panel.isVisible()
            and not self._visualizer_panel.geometry().contains(pos)
        ):
            self._hide_visualizer_panel()
            return

        # Progress slider only responds when a track is loaded.
        if self._current_track and self._progress_bar_rect.contains(pos):
            self._drag_target = "progress"
            self._progress_slider.dragging = True
            self._update_drag_value(pos)
            self.update()
            return

        # Volume slider always responds.
        if self._volume_bar_rect.contains(pos):
            self._drag_target = "volume"
            self._volume_slider.dragging = True
            self._update_drag_value(pos)
            self.update()
            return

        # Vinyl record / sleeve interaction.
        on_record = False
        if self._current_track and self._vinyl_record_radius > 0:
            dx = pos.x() - self._vinyl_record_center.x()
            dy = pos.y() - self._vinyl_record_center.y()
            if dx * dx + dy * dy <= self._vinyl_record_radius * self._vinyl_record_radius:
                on_record = True

        if on_record and self._vinyl_out_progress >= 0.95:
            # Merely pressing the record arms the scratch; the platter is only
            # grabbed once the pointer actually moves. That keeps the
            # throw-back drag (press the label, pull right) from producing a
            # scratch on its way out, which it did when the grab happened here.
            self._vinyl_dragging = True
            self._vinyl_scratch_armed = True
            # Only a press on the paper label may become a throw-back; from the
            # outer black disc a rightward drag is just a scratch, so the record
            # never flies back to the sleeve mid-scratch.
            self._vinyl_press_pos = pos
            self._vinyl_drag_origin = pos if self._on_vinyl_label(pos) else None
            # Snapshot the audio position now, so it shares an instant with the
            # angle baseline even though the scratch engages a move later.
            if self._audio_backend == "pcm" and self._engine is not None:
                self._vinyl_press_audio_ms = self._engine.position_ms()
            elif self._player is not None:
                self._vinyl_press_audio_ms = self._player.position()
            else:
                self._vinyl_press_audio_ms = 0
            self._vinyl_angular_velocity = 0.0
            self._vinyl_scratch_delta = 0.0
            self._vinyl_scratch_start_angle = math.atan2(
                pos.y() - self._vinyl_record_center.y(),
                pos.x() - self._vinyl_record_center.x(),
            )
            self._vinyl_last_mouse_angle = self._vinyl_scratch_start_angle
            self._vinyl_drag_timer.start()
            self._update_cursor()
            self.update()
            return

        if self._current_track and self._vinyl_out_progress <= 0.05:
            # Stowed: only the sliver peeking out of the sleeve is grabbable.
            # Pressing it starts a pull-that-may-become-a-click; dragging left
            # slides the record out by hand, while a plain click still pulls it
            # out on its own.
            if self._vinyl_peek_rect().contains(pos):
                self._vinyl_pull_origin = pos
                self._vinyl_pull_start_progress = self._vinyl_out_progress
                self._vinyl_pull_active = False
                self._vinyl_out_anim.stop()
                self.update()
                return

        # Play/pause only works when a track is loaded.
        if self._current_track and self._play_btn_rect.contains(pos):
            self._press_button("play" if self._is_playing else "pause")
            self._play_pause()
            return

        if self._prev_btn_rect.contains(pos):
            self._press_button("previous")
            self._previous_track()
            return

        if self._next_btn_rect.contains(pos):
            self._press_button("next")
            self._next_track()
            return

        # Music folder / menu button.
        if self._folder_btn_rect.contains(pos):
            self._press_button("menu" if self._music_dir else "folder")
            if self._music_dir:
                self._toggle_music_menu()
            else:
                self._open_music_dir()
            return

        # Clear hover when pressing empty space.

        # Begin a lyrics drag/click on the right-hand lyrics panel.
        if (
            self._lyrics_panel_rect.isValid()
            and self._lyrics_panel_rect.contains(pos)
            and self._lyrics
        ):
            self._lyrics_dragging = True
            self._lyrics_drag_moved = False
            self._lyrics_drag_start_y = pos.y()
            self._lyrics_scroll_at_drag_start = self._lyrics_scroll_offset
            self._lyrics_auto_follow = False
            self._lyrics_resume_timer.stop()
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._mouse = event.position()
        pos = event.position().toPoint()

        self._volume_slider.hovered = self._volume_bar_rect.contains(pos)
        self._progress_slider.hovered = (
            self._current_track is not None
            and self._progress_bar_rect.contains(pos)
        )

        # Which lyric line the pointer is over. The region decides whether it is over the lyrics at
        # all -- the gaps between lines count -- and the index is only used to tell "off the lyrics"
        # from "on them", so any line in the region will do. Resolving it by exact rectangle left the
        # index at -1 in every gap, which cancelled the hover entirely.
        #
        # Only repaint when it actually changes, since this runs on every move.
        active_now = self._current_lyric_index() if self._lyrics else -1
        if self._lyrics and self._lyrics_region_contains(pos.x(), pos.y(), active_now):
            hovered = self._lyrics_index_near(pos.y(), active_now)
            if hovered < 0:
                hovered = -2      # in the region but between lines: still "over the lyrics"
        else:
            hovered = -1
        if hovered != self._lyrics_hover_index:
            self._lyrics_hover_index = hovered
            self.update()

        if self._vinyl_pull_origin is not None and not self._vinyl_pull_active:
            # Waiting to see whether this is a hand pull or just a click.
            dx = pos.x() - self._vinyl_pull_origin.x()
            if abs(dx) >= VINYL_PULL_DRAG_PX:
                # Re-anchor at the point the drag engages. Without this the
                # travel already spent reaching the threshold lands in one go
                # and the record visibly jumps as the drag starts.
                self._vinyl_pull_active = True
                self._vinyl_pull_origin = pos
                self._vinyl_pull_start_progress = self._vinyl_out_progress
                self.update()
                return

        if self._vinyl_pull_active:
            # Map the pointer's travel onto the record's own travel so the
            # record tracks the hand exactly, rather than moving at a fixed rate.
            dx = pos.x() - self._vinyl_pull_origin.x()
            progress = self._vinyl_pull_start_progress - dx / self._vinyl_travel_px()
            self._vinyl_out_progress = max(0.0, min(1.0, progress))
            self._vinyl_out = self._vinyl_out_progress > 0.5
            self._update_cursor()
            self.update()
            return

        if self._vinyl_dragging:
            # A press on the centre label is a candidate for the throw-back
            # gesture, so it does NOT start scratching yet: doing so would spin
            # the platter for the first few pixels of every stow. It waits until
            # the pointer either passes the stow threshold or proves it is a
            # scratch by going left or mostly vertically. A press anywhere else
            # on the disc scratches on the first movement.
            origin = self._vinyl_drag_origin
            if origin is not None and self._vinyl_scratch_armed:
                dx = pos.x() - origin.x()
                dy = pos.y() - origin.y()
                if dx >= VINYL_STOW_DRAG_PX and abs(dy) < dx:
                    self._stow_vinyl()
                    return
                if dx < 0 or abs(dy) > max(4.0, abs(dx)):
                    self._begin_scratch()
                else:
                    # Ambiguous so far: rightward but not far enough to stow.
                    self.update()
                    return
            else:
                # No origin means the grab started on the black disc; an
                # already-engaged scratch simply continues.
                self._begin_scratch()

            center = self._vinyl_record_center
            angle = math.atan2(pos.y() - center.y(), pos.x() - center.x())
            diff = math.atan2(
                math.sin(angle - self._vinyl_last_mouse_angle),
                math.cos(angle - self._vinyl_last_mouse_angle),
            )
            delta_deg = math.degrees(diff)
            self._scratch_rotation_deg += delta_deg
            self._vinyl_angle = self._scratch_rotation_deg % 360.0
            self._vinyl_scratch_delta += delta_deg
            self._vinyl_scratch_delta = max(
                -VINYL_MAX_SCRATCH_DELTA_DEG,
                min(VINYL_MAX_SCRATCH_DELTA_DEG, self._vinyl_scratch_delta),
            )

            elapsed = self._vinyl_drag_timer.restart()
            if elapsed > 0:
                velocity = delta_deg / elapsed
                # Clamp single-event spikes so one bad event doesn't explode,
                # then smooth (EMA) so audio rate and visuals don't jitter.
                velocity = max(-5.0, min(5.0, velocity))
                self._vinyl_angular_velocity += (
                    velocity - self._vinyl_angular_velocity
                ) * VINYL_VEL_EMA
            self._vinyl_last_mouse_angle = angle

            # PCM engine: drive the playhead right here for the lowest
            # possible latency between the hand and the needle.
            if self._audio_backend == "pcm" and self._engine is not None:
                self._engine.set_playhead_ms(self._desired_scratch_position_raw())
            self.update()
            return

        if self._lyrics_dragging:
            delta = pos.y() - self._lyrics_drag_start_y
            if abs(delta) > 8:
                self._lyrics_drag_moved = True
            self._lyrics_scroll_offset = (
                self._lyrics_scroll_at_drag_start - delta
            )
            panel_w = int(self.width() * 0.5 * self._lyrics_progress)
            self._clamp_lyrics_scroll_offset(max(20, panel_w - 60))
            self.update()
            return

        self._update_cursor()
        if self._drag_target:
            self._update_drag_value(pos)
            self.update()
        elif self._volume_slider.hovered or self._progress_slider.hovered:
            self.update()

    def _update_cursor(self) -> None:
        """Grabby hand cursor over the pullable record, closed while scratching."""
        if self._vinyl_dragging:
            shape = Qt.ClosedHandCursor
        elif (
            self._current_track
            and self._vinyl_record_radius > 0
            and self._vinyl_out_progress >= 0.95
        ):
            dx = self._mouse.x() - self._vinyl_record_center.x()
            dy = self._mouse.y() - self._vinyl_record_center.y()
            on_record = (
                dx * dx + dy * dy
                <= self._vinyl_record_radius * self._vinyl_record_radius
            )
            shape = Qt.OpenHandCursor if on_record else None
        else:
            shape = None
        if shape != self._cursor_shape:
            self._cursor_shape = shape
            if shape is None:
                self.unsetCursor()
            else:
                self.setCursor(shape)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        old_target = self._drag_target
        self._mouse_down = False
        self._progress_slider.dragging = False
        self._volume_slider.dragging = False
        self._drag_target = None

        if self._vinyl_pull_origin is not None:
            # Releasing a hand pull: carry on out to the end if the pointer made
            # it past halfway, otherwise settle back into the sleeve. A plain
            # click (no drag at all) still pulls the record out on its own.
            if not self._vinyl_pull_active:
                self._set_vinyl_out(True)
            elif self._vinyl_out_progress >= 0.5:
                self._set_vinyl_out(True)
            else:
                self._set_vinyl_out(False)
            self._vinyl_pull_origin = None
            self._vinyl_pull_active = False
            self.update()
            return

        if old_target == "progress" and self._duration > 0:
            self._seek_to(self._progress_slider.target * self._duration)
        elif old_target == "volume":
            self._set_volume(self._volume_slider.target)

        if self._lyrics_dragging:
            pos = event.position().toPoint()
            if not self._lyrics_drag_moved and self._lyrics_hit_rects:
                # Treat as a click: seek to the clicked lyric if it has a timestamp.
                for rect, idx in self._lyrics_hit_rects:
                    if rect.contains(pos):
                        t, _ = self._lyrics[idx]
                        if t >= 0:
                            self._seek_to(t * 1000)
                            self._lyrics_auto_follow = True
                        break
            else:
                # Drag finished: resume auto-follow after a short pause.
                self._lyrics_resume_timer.start(2000)
            self._lyrics_dragging = False
            self._lyrics_drag_moved = False
            self.update()

        if self._vinyl_dragging:
            self._end_scratch()

    def leaveEvent(self, event) -> None:  # noqa: N802
        """End an active scratch if the cursor leaves the widget."""
        if self._vinyl_dragging:
            self._end_scratch()
        # Drop the hovered lyric too. Without this the last line pointed at would stay at full
        # strength after the cursor has gone, which reads as a stuck highlight.
        if self._lyrics_hover_index != -1:
            self._lyrics_hover_index = -1
            self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Scroll the lyrics panel with the mouse wheel."""
        pos = event.position().toPoint()
        if (
            self._lyrics_panel_rect.isValid()
            and self._lyrics_panel_rect.contains(pos)
            and self._lyrics
        ):
            delta = event.angleDelta().y()
            if delta != 0:
                self._lyrics_auto_follow = False
                self._lyrics_resume_timer.stop()
                self._lyrics_scroll_offset -= delta * 0.8
                panel_w = int(self.width() * 0.5 * self._lyrics_progress)
                self._clamp_lyrics_scroll_offset(max(20, panel_w - 60))
                # Resume auto-follow after the user stops wheeling.
                self._lyrics_resume_timer.start(2000)
                self.update()
                return
        super().wheelEvent(event)

    def _update_drag_value(self, pos: QPoint) -> None:
        if self._drag_target == "progress":
            rect = self._progress_bar_rect
            value = (
                (pos.x() - rect.left()) / rect.width() if rect.width() else 0.0
            )
            self._progress_slider.set_target(value)
        elif self._drag_target == "volume":
            rect = self._volume_bar_rect
            icon_w = 20
            gap = 10
            inner_x = rect.left() + icon_w + gap
            inner_w = rect.width() - (icon_w + gap) * 2
            value = (
                (pos.x() - inner_x) / inner_w if inner_w else 0.0
            )
            self._volume_slider.set_target(value)
            self._set_volume(value)
