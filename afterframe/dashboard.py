import math
import random
import time
from typing import Dict, Optional

import psutil

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .constants import APP_VERSION, HEADING_WEIGHT, ui_font

# ---------------------------------------------------------------------------
# Atmospheric speed-line effect (white / blue anime slash-burst style)
# ---------------------------------------------------------------------------
FX_BG_TOP = QColor(243, 246, 251)
FX_BG_BOTTOM = QColor(255, 255, 255)
FX_NAVY = QColor(30, 42, 62)
FX_FLOOR = QColor(152, 184, 224)
# How much the checker floor borrows from a playing track's rhythm (see
# `set_rhythm_source`). Only the MOTION and the brightness follow the music --
# the floor keeps its own colours, it never takes the cover's palette the way the
# music page's checkerboard does.
FLOOR_RHYTHM_SPEEDUP = 1.6  # scroll speed multiplier at full loudness
FLOOR_BEAT_KICK = 0.7  # extra scroll on a beat
FLOOR_RHYTHM_GAIN = 0.55  # cell brightness lift at full loudness
FLOOR_BEAT_FLASH = 0.5  # extra cell brightness on a beat
# Cool-grey glass used by the metric cards and the detail panel.
GLASS_TINT = QColor(30, 42, 62)

# How far the card shadow reaches beyond the panel.
#
# The panel is inset from its widget by SHADOW_PAD, which has to be at least this
# (plus the hover lift) or the shadow is cut off at the widget boundary. The rings in
# `paint_glass_panel` step inward by one pixel from here.
SHADOW_SPREAD = 14.0

# Total strength of the card shadow, as a fraction of GLASS_TINT.
#
# This is the opacity at the panel's edge; the blur tapers it to nothing at
# SHADOW_SPREAD. Hovering scales it up slightly rather than recomputing anything.
SHADOW_TINT = 0.55

# How hard the shadow is blurred, as the divisor for a downscale-then-upscale pass.
#
# A real blur is needed here rather than stacked shapes: the falloff spans only
# SHADOW_SPREAD pixels and the alpha channel has 255 levels, so any shape-stacking
# scheme quantises into flat runs -- measured as a 7 px plateau along the bottom edge
# at rest and 12 px while hovered, which stayed put through two attempts to derive the
# per-shape alphas better. Downscaling past the pen's resolution and upscaling smoothly
# produces the intermediate levels the 255-step ramp cannot.
#
# The upscale path is expensive for a large pixmap (a few ms felt on a live resize), so
# the result is cached in _SHADOW_CACHE, and it depends only on size, radius and device
# pixel ratio -- not on hover, which is applied as a draw-time alpha.
_SHADOW_BLUR_DIVISOR = 6

# How much tighter the shadow's corner is than the panel's, in logical pixels.
#
# The panel's corner radius pulls its own edge a long way in from the bounding box; if the
# shadow used the same radius and the blur could not reach that far, the corners ended up
# with no shadow at all instead of a lighter one (measured along the arc: peak alpha 58 at
# inset 0, against 255 on a straight edge -- effectively nothing).
#
# The value trades corner shadow against edge shadow, measured as the peak alpha along the
# visible arc, against 107 on a straight edge:
#
#     inset 0  ->  58 (no shadow at all)     inset 7  -> 126 (heavier than the edges)
#     inset 3  ->  89                        inset 9  -> 134
#     inset 4  -> 100                        inset 16 -> 140 (one-pixel radius)
#
# 7 fixed the missing corner but out-weighed the sides; 4 read as still a touch heavy, so
# this sits at 3 -- clearly present, clearly lighter than the straight edges.
SHADOW_CORNER_INSET = 3.0
_SHADOW_CACHE: dict = {}
_SHADOW_CACHE_LIMIT = 32


def _blurred_shadow(rect: QRectF, radius: float, dpr: float):
    """A blurred drop shadow for *rect*, as (pixmap, top-left point).

    The pixmap is the shadow COLOURED, not a white mask: its alpha is the blur profile and
    its RGB is GLASS_TINT scaled by SHADOW_TINT. It has to be coloured here because
    drawing white-with-alpha onto the page's near-white background composites to nothing
    -- which is exactly how the first blurred attempt "drew nothing" while every property
    of the pixmap measured correct.

    The shadow is a rounded rect SHADOW_SPREAD larger than the panel on every side,
    blurred and then hollowed out, and it is cached: the shape depends only on the size,
    the radius and the device pixel ratio, while this is called from paintEvent on cards
    that repaint every frame while the dashboard animates.

    A real blur is used rather than stacked shapes because the falloff spans a limited
    number of pixels while the alpha channel has 255 levels. Three hard-edged rectangles
    produced 10-12 level steps; rings whose alphas were derived from the wanted taper
    still measured a 7 px plateau along the bottom edge at rest and 12 px hovered, because
    accumulating quantised shapes cannot produce the intermediate levels a blur does.

    The blur is the same trick used elsewhere in this code -- downscale, then upscale
    smoothly, through two intermediate hops. One hop was measured to leave a ramp tighter
    than the shadow it sat in.

    Returns (None, None) when there is nothing sensible to draw.
    """
    key = (round(rect.width(), 1), round(rect.height(), 1), round(radius, 1), round(dpr, 3))
    cached = _SHADOW_CACHE.get(key)
    if cached is not None:
        return cached

    pad = SHADOW_SPREAD
    if rect.width() <= 0 or rect.height() <= 0:
        return None, None

    dev_w = max(1, int(round((rect.width() + pad * 2) * dpr)))
    dev_h = max(1, int(round((rect.height() + pad * 2) * dpr)))

    # 1) The shape at device resolution, opaque white -- a mask to be coloured later.
    #
    # The shadow's corner is deliberately TIGHTER than the panel's. With the same radius
    # the shape's edge pulls 32 device pixels in from the bounding box corner (radius 16
    # logical at dpr 2), while the blur only reaches about 10 device pixels -- so there was
    # no material left near the corner and the shadow vanished there rather than merely
    # fading. Measured at the top-left corner, the alpha was 0 across a 20x20 device window
    # where the straight edge reached 59. A squarer corner keeps material within the blur's
    # reach; the panel body drawn on top hides the difference in shape.
    shadow_radius = max(1.0, radius - SHADOW_CORNER_INSET) * dpr
    shape = QPixmap(dev_w, dev_h)
    shape.fill(Qt.transparent)
    sp = QPainter(shape)
    sp.setRenderHint(QPainter.Antialiasing)
    sp.setPen(Qt.NoPen)
    sp.setBrush(Qt.white)
    sp.drawRoundedRect(
        QRectF(pad * dpr, pad * dpr, rect.width() * dpr, rect.height() * dpr),
        shadow_radius, shadow_radius,
    )
    sp.end()

    # 2) Blur: shrink past the outline's own resolution, then grow back in hops. The blur
    #    radius lands around (divisor - 1) device pixels, so it has to stay a fraction of
    #    the shadow's reach: at reach 14 device px a divisor of 3 left a ramp falling
    #    94 -> 0 within 6 px, and at divisor 5 the edge alpha was diluted until the whole
    #    shadow composited to a single level.
    small = shape.scaled(max(1, dev_w // _SHADOW_BLUR_DIVISOR),
                         max(1, dev_h // _SHADOW_BLUR_DIVISOR),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    middle_a = small.scaled(max(1, dev_w // 4), max(1, dev_h // 4),
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    middle_b = middle_a.scaled(max(1, dev_w // 2), max(1, dev_h // 2),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blurred = middle_b.scaled(dev_w, dev_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    # 3) Hollow it out, so the panel's own translucent body is not darkened underneath.
    hp = QPainter(blurred)
    hp.setRenderHint(QPainter.Antialiasing)
    hp.setCompositionMode(QPainter.CompositionMode_Clear)
    hp.setPen(Qt.NoPen)
    hp.setBrush(Qt.white)
    hp.drawRoundedRect(
        QRectF(pad * dpr, pad * dpr, rect.width() * dpr, rect.height() * dpr),
        radius * dpr, radius * dpr,
    )
    hp.end()

    # 4) Colourise: replace the white with the shadow tint, keeping the alpha profile.
    #    SourceIn leaves the alpha alone and paints the colour only where alpha exists.
    cp = QPainter(blurred)
    cp.setCompositionMode(QPainter.CompositionMode_SourceIn)
    tint = QColor(GLASS_TINT)
    tint.setAlphaF(min(1.0, SHADOW_TINT))
    cp.fillRect(blurred.rect(), tint)
    cp.end()

    # The pixmap holds DEVICE pixels, so it must say so, or drawPixmap lays it out at one
    # logical pixel each and the shadow lands twice the intended size.
    blurred.setDevicePixelRatio(dpr)

    origin = QPointF(rect.left() - pad, rect.top() - pad)
    if len(_SHADOW_CACHE) >= _SHADOW_CACHE_LIMIT:
        _SHADOW_CACHE.clear()
    _SHADOW_CACHE[key] = (blurred, origin)
    return blurred, origin


def paint_glass_panel(
    painter: QPainter,
    rect: QRectF,
    radius: float = 16.0,
    hovered: bool = False,
    shadow: bool = True,
    solidity: float = 0.0,
) -> None:
    """Paint a cool-grey frosted-glass panel with a lit top edge.

    Layered by hand (soft shadow, tinted gradient body, top highlight and a
    brighter upper border) because a stylesheet cannot express the glass look:
    no drop shadow, no separate lit edge.

    *solidity* (0..1) pushes the body toward fully opaque; the metric cards
    stay translucent while the detail panel needs to stay readable.
    """
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    def mix(alpha: int) -> int:
        return int(alpha + (255 - alpha) * max(0.0, min(1.0, solidity)))

    if shadow:
        # Hovering lifts the card: the same shape, drawn a little stronger. The shape
        # itself does not change, so the cached blur is reused and only the alpha at
        # draw time differs.
        painter.setPen(Qt.NoPen)
        shadow_pix, origin = _blurred_shadow(rect, radius, painter.device().devicePixelRatio())
        if shadow_pix is not None:
            # Hover just draws it a little more strongly; the blurred pixmap already
            # carries the tint and the alpha profile.
            painter.save()
            if hovered:
                painter.setOpacity(1.25)
            painter.drawPixmap(origin, shadow_pix)
            painter.restore()

    # Translucent cool-grey body: light at the top, cooler and denser at the
    # bottom, so the page behind stays faintly visible through the glass.
    # Hover deepens the cool tint at the same opacity: against a bright page,
    # opacity changes barely read.
    bottom_tint = QColor(204, 221, 246, mix(158)) if hovered else QColor(222, 233, 248, mix(158))
    body = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    body.setColorAt(0.0, QColor(252, 254, 255, mix(170)))
    body.setColorAt(1.0, bottom_tint)
    painter.setPen(Qt.NoPen)
    painter.setBrush(body)
    painter.drawPath(path)

    # Glossy highlight washing over the upper half; brightening it is what
    # makes hovered glass look lit up.
    painter.save()
    painter.setClipPath(path)
    half = QLinearGradient(
        rect.topLeft(), QPointF(rect.left(), rect.top() + rect.height() * 0.55)
    )
    half.setColorAt(0.0, QColor(255, 255, 255, 250 if hovered else 165))
    half.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(half)
    painter.drawRect(rect)
    painter.restore()

    # Bright upper edge where the glass catches the light. Drawn BEFORE the
    # border so the border always stays a clean, continuous outline: drawing it
    # on top made the two 1 px lines fight over the corner arcs.
    painter.save()
    painter.setClipRect(
        QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.5)
    )
    painter.setPen(QPen(QColor(255, 255, 255, 210), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()

    # Cool border, on top, so the outline follows the rounded corners exactly.
    # On hover the edge turns cool blue, which is what makes the state read
    # clearly even against a bright page.
    if hovered:
        border = QColor(64, 112, 188, 135)
    else:
        border = QColor(GLASS_TINT)
        border.setAlpha(34)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(border, 1))
    painter.drawPath(path)

MAX_STREAKS = 24


class _Streak:
    """A fast ambient speed line flying across the page."""

    def __init__(self, w: float, h: float, origin: Optional[QPointF] = None) -> None:
        self.max_life = random.uniform(0.5, 1.1)
        self.life = self.max_life
        alpha_base = random.uniform(90, 200)
        kind = random.choices(("white", "blue", "navy"), weights=(0.5, 0.35, 0.15))[0]
        self.color = {
            "white": QColor(255, 255, 255, int(alpha_base)),
            "blue": QColor(126, 160, 214, int(alpha_base * 0.85)),
            "navy": QColor(38, 54, 80, int(alpha_base * 0.7)),
        }[kind]

        if origin is not None:
            self.x = origin.x()
            self.y = origin.y()
            ang = random.uniform(0.0, math.tau)
            speed = random.uniform(500.0, 1200.0)
        else:
            # Spawn just off a random edge, aimed across the page.
            edge = random.random()
            if edge < 0.5:
                self.x = -20 if random.random() < 0.5 else w + 20
                self.y = random.uniform(0, h)
                ang = 0.0 if self.x < 0 else math.pi
                ang += random.uniform(-0.35, 0.35)
            else:
                self.x = random.uniform(0, w)
                self.y = -20 if random.random() < 0.5 else h + 20
                ang = math.pi / 2 if self.y < 0 else -math.pi / 2
                ang += random.uniform(-0.35, 0.35)
            speed = random.uniform(600.0, 1500.0)

        self.vx = math.cos(ang) * speed
        self.vy = math.sin(ang) * speed
        self.length = random.uniform(70.0, 260.0)
        self.width = random.uniform(1.0, 3.2)

    def step(self, dt: float, w: float, h: float) -> bool:
        self.life -= dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        margin = 260
        if self.life <= 0:
            return False
        if not (-margin < self.x < w + margin and -margin < self.y < h + margin):
            return False
        return True

    def draw(self, p: QPainter) -> None:
        fade = min(1.0, self.life / (self.max_life * 0.5))
        color = QColor(self.color)
        color.setAlpha(int(color.alpha() * fade))
        speed = math.hypot(self.vx, self.vy)
        if speed <= 0:
            return
        ux = self.vx / speed
        uy = self.vy / speed
        pen = QPen(color)
        pen.setWidthF(self.width)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(
            QPointF(self.x - ux * self.length, self.y - uy * self.length),
            QPointF(self.x, self.y),
        )


class MetricCard(QFrame):
    """A clickable cool-grey glass card showing one system metric."""

    clicked = Signal()

    # Room inside the widget for the soft drop shadow. It MUST be at least
    # SHADOW_SPREAD, or the shadow is clipped by the widget's own bounds; the +2 leaves
    # a pixel of slack for the rounded corner's antialiasing.
    SHADOW_PAD = int(SHADOW_SPREAD) + 2
    RADIUS = 16.0

    def __init__(
        self,
        title: str,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)

        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._hovered = False
        self._glass_pix: QPixmap | None = None
        self._glass_key = None

        layout = QVBoxLayout(self)
        # Extra padding equal to the shadow inset keeps the content at the same
        # distance from the painted glass body.
        layout.setContentsMargins(20 + self.SHADOW_PAD, 18 + self.SHADOW_PAD,
                                  20 + self.SHADOW_PAD, 18 + self.SHADOW_PAD)
        layout.setSpacing(10)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(
            "color: rgba(30, 42, 62, 0.60); font-size: 13px; background: transparent;"
        )
        layout.addWidget(self._title_label)

        self._value_label = QLabel("--")
        value_font = ui_font(32)
        value_font.setWeight(HEADING_WEIGHT)
        self._value_label.setFont(value_font)
        self._value_label.setStyleSheet("color: #1E2A3E; background: transparent;")
        layout.addWidget(self._value_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet("""
            QProgressBar {
                background-color: rgba(30, 42, 62, 0.10);
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #76B900;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self._progress)

        self._sub_label = QLabel("")
        self._sub_label.setStyleSheet(
            "color: rgba(30, 42, 62, 0.48); font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._sub_label)

        # Let the card itself receive hover/click events so the glass highlight
        # reacts reliably, no matter which label is under the cursor.
        for child in (self._title_label, self._value_label, self._progress, self._sub_label):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        # The glass body (shadow, gradients, lit edges, border) is expensive and
        # only changes with size or hover, so it is rendered once into a pixmap
        # and blitted afterwards - the dashboard repaints every frame.
        key = (self.width(), self.height(), self._hovered)
        if self._glass_key != key or self._glass_pix is None:
            # The pixmap must be built in DEVICE pixels and told its ratio, otherwise it
            # holds a half-resolution picture at 200% that gets upscaled when blitted --
            # which turns the antialiased corner arc into a visible staircase. Measured on
            # the arc: with a logical-size pixmap the corner showed 2-5 distinct coverage
            # levels and no partial values at all (a hard stepped edge); device-sized, the
            # arc is smooth.
            ratio = self.devicePixelRatioF() or 1.0
            pixmap = QPixmap(
                max(1, int(round(self.width() * ratio))),
                max(1, int(round(self.height() * ratio))),
            )
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.transparent)
            glass = QPainter(pixmap)
            glass.setRenderHint(QPainter.Antialiasing)
            pad = self.SHADOW_PAD
            # Half-pixel inset so the 1 px border lands on pixel centres:
            # crisper line, corners concentric with the glass body.
            body = QRectF(self.rect()).adjusted(
                pad + 0.5, pad + 0.5, -pad - 0.5, -pad - 0.5
            )
            paint_glass_panel(glass, body, self.RADIUS, hovered=self._hovered)
            glass.end()
            self._glass_pix = pixmap
            self._glass_key = key

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._glass_pix)

    def set_value(self, value: float, sub_text: str = "") -> None:
        clamped = max(0.0, min(100.0, value))
        self._progress.setValue(int(clamped))
        self._value_label.setText(f"{clamped:.0f}%")
        self._sub_label.setText(sub_text)

    def set_custom_value(self, text: str, sub_text: str = "") -> None:
        self._value_label.setText(text)
        self._sub_label.setText(sub_text)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.clicked.emit()


class DetailPanel(QFrame):
    """Expanded detail view for a metric, animated in/out over the dashboard."""

    closed = Signal()

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, False)
        # The glass body is painted in paintEvent; only the children are styled.
        self.setStyleSheet("""
            DetailPanel {
                background-color: transparent;
                border: none;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        self._title_label = QLabel("Detail")
        title_font = ui_font(18)
        title_font.setWeight(HEADING_WEIGHT)
        self._title_label.setFont(title_font)
        self._title_label.setStyleSheet("color: #1E2A3E; background: transparent;")
        header.addWidget(self._title_label)
        header.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(30, 42, 62, 0.65);
                border: 1px solid rgba(30, 42, 62, 0.18);
                border-radius: 14px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: rgba(30, 42, 62, 0.08);
                color: #1E2A3E;
            }
        """)
        close_btn.clicked.connect(self.closed.emit)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 5px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(30, 42, 62, 0.24);
                border-radius: 2px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(30, 42, 62, 0.42);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        self._content = QVBoxLayout(content_widget)
        self._content.setContentsMargins(0, 0, 6, 0)
        self._content.setSpacing(12)
        self._scroll.setWidget(content_widget)
        layout.addWidget(self._scroll, 1)

    def clear(self) -> None:
        while self._content.count():
            item = self._content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802
        """Same cool-grey glass as the cards it expands from, but denser so
        the text inside stays comfortably readable."""
        painter = QPainter(self)
        paint_glass_panel(
            painter,
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            20.0,
            shadow=False,
            solidity=0.9,
        )

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                DetailPanel._clear_layout(item.layout())
                item.layout().deleteLater()

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def add_row(self, label: str, value: str) -> None:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "color: rgba(30, 42, 62, 0.55); font-size: 12px; background: transparent;"
        )
        val = QLabel(value)
        val.setStyleSheet(
            "color: #1E2A3E; font-size: 12px; background: transparent;"
        )
        val.setAlignment(Qt.AlignRight)
        layout.addWidget(lbl)
        layout.addStretch()
        layout.addWidget(val)
        self._content.addWidget(container)

    def add_bar(self, label: str, percent: float) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "color: rgba(30, 42, 62, 0.70); font-size: 11px; background: transparent;"
        )
        val = QLabel(f"{percent:.0f}%")
        val.setStyleSheet(
            "color: rgba(30, 42, 62, 0.70); font-size: 11px; background: transparent;"
        )
        val.setAlignment(Qt.AlignRight)
        top.addWidget(lbl)
        top.addStretch()
        top.addWidget(val)
        layout.addLayout(top)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(max(0, min(100, percent))))
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(30, 42, 62, 0.08);
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #76B900;
                border-radius: 2px;
            }
        """)
        layout.addWidget(bar)
        self._content.addWidget(container)


class SystemDashboard(QWidget):
    """Full-page system monitor with expandable metric cards."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)

        self._last_net_time: Optional[float] = None
        self._last_net_sent: int = 0
        self._last_net_recv: int = 0
        self._active_detail: Optional[str] = None
        self._open_anim = None
        self._close_anim = None

        # While a page switch animates this page it is repainted by the
        # animation itself, so the 60 fps background update is skipped.
        self._switching = False

        # Speed-line effect state.
        self._streaks: list[_Streak] = []
        self._fx_time = 0.0
        self._floor_scroll = 0.0  # checker phase, in row units
        # Borrowed music rhythm: (loudness, beat impulse) from the music page,
        # zero whenever nothing is playing. Set by the window.
        self._rhythm_source = None
        self._rhythm_level = 0.0
        self._rhythm_beat = 0.0
        self._fx_clock = time.monotonic()
        self._fx_timer = QTimer(self)
        self._fx_timer.setInterval(16)
        self._fx_timer.timeout.connect(self._fx_tick)

        # Prime CPU percent so the first real reading is meaningful.
        psutil.cpu_percent(interval=None)

        self._setup_ui()
        self._update()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(1000)

    # ------------------------------------------------------------------
    # Atmospheric effect layer
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fx_clock = time.monotonic()
        self._fx_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._fx_timer.stop()

    def set_rhythm_source(self, source) -> None:
        """Borrow another page's music rhythm for the checker floor.

        *source* is called with no arguments and returns (loudness, beat impulse),
        both 0..1-ish and both zero while nothing is playing. The floor's colours
        stay its own -- this only drives its speed and brightness.
        """
        self._rhythm_source = source

    def _pull_rhythm(self) -> None:
        """Refresh the borrowed rhythm, treating any failure as 'not playing'."""
        level, beat = 0.0, 0.0
        if self._rhythm_source is not None:
            try:
                level, beat = self._rhythm_source()
            except Exception:
                level, beat = 0.0, 0.0
        self._rhythm_level = max(0.0, min(1.2, float(level)))
        self._rhythm_beat = max(0.0, min(1.0, float(beat)))

    def _fx_tick(self) -> None:
        now = time.monotonic()
        dt = max(0.0, min(now - self._fx_clock, 0.1))
        self._fx_clock = now
        self._fx_time += dt
        self._pull_rhythm()
        # The floor scrolls with a slowly breathing speed so its motion never
        # reads as a fixed loop. While music plays it borrows that music's
        # rhythm: louder drifts faster, and a beat gives it a kick.
        drift = 0.16 + 0.05 * math.sin(self._fx_time * 0.35)
        self._floor_scroll += dt * drift * (
            1.0
            + FLOOR_RHYTHM_SPEEDUP * self._rhythm_level
            + FLOOR_BEAT_KICK * self._rhythm_beat
        )
        w = max(1, self.width())
        h = max(1, self.height())

        # Ambient streaks.
        if len(self._streaks) < MAX_STREAKS and random.random() < 0.55:
            self._streaks.append(_Streak(w, h))

        self._streaks = [s for s in self._streaks if s.step(dt, w, h)]
        if not self._switching:
            self.update()

    def set_switching(self, active: bool) -> None:
        """Called by PageStack during page-switch animations.

        The animation repaints this whole page every frame, so the extra
        background refresh is skipped to leave the frame budget to it.
        """
        self._switching = active
        if not active:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        # Bright cool-white gradient base. A plain fill - no antialiasing
        # needed for an axis-aligned rectangle.
        painter.setRenderHint(QPainter.Antialiasing, False)
        bg = QLinearGradient(0, 0, w * 0.25, h)
        bg.setColorAt(0.0, FX_BG_TOP)
        bg.setColorAt(1.0, FX_BG_BOTTOM)
        painter.setBrush(bg)
        painter.drawRect(0, 0, w, h)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Perspective checker floor along the bottom edge.
        self._draw_checker(painter, w, h)

        # Ambient streaks.
        for streak in self._streaks:
            streak.draw(painter)

        # Crisp HUD decorations above the effect layer.
        self._draw_hud(painter, w, h)

    def _draw_checker(self, painter: QPainter, w: float, h: float) -> None:
        """Faint perspective checker floor with a seamless infinite scroll.

        Two things keep the loop invisible:
        - The phase wraps over an EVEN number of rows, so checker parity is
          identical at the wrap point (a 1-row wrap would visibly invert
          every cell once per cycle).
        - Cell brightness is modulated by a pattern fixed in SCREEN space
          (not attached to the sliding tiles), so no two moments show the
          same arrangement of shades.
        """
        painter.save()
        # Faint wash: antialiasing is invisible here but costs ~2.4x.
        painter.setRenderHint(QPainter.Antialiasing, False)

        horizon = h * 0.865
        depth = h - horizon
        if depth < 8:
            painter.restore()
            return
        rows = 9
        cols = 18
        spread = w * 1.15
        scroll = self._floor_scroll % 2.0
        # Music lifts the floor's brightness and a beat flashes it -- the same
        # reaction the music page's checkerboard has, but with THIS page's colour
        # (FX_FLOOR), never the cover's palette.
        rhythm = 1.0 + FLOOR_RHYTHM_GAIN * self._rhythm_level
        flash = min(1.0, self._rhythm_beat * 0.9)

        for row in range(-2, rows + 2):
            f0 = (row + scroll) / rows
            f1 = (row + 1 + scroll) / rows
            if f1 <= 0.0 or f0 >= 1.0:
                continue
            y0 = horizon + depth * (max(f0, 0.0) ** 2.0)
            y1 = horizon + depth * (min(f1, 1.0) ** 2.0)
            if y1 - y0 < 0.5:
                continue
            s0 = max(0.02, f0)
            s1 = min(1.0, max(0.03, f1))
            base_alpha = 52 * (s0 ** 1.25)
            if base_alpha <= 1.2:
                continue
            for col in range(cols):
                if (row + col) % 2:
                    continue
                # Screen-space sheen: fixed light pattern over moving tiles.
                var = 0.85 + 0.15 * math.sin((y0 / h) * 9.2 + col * 1.31)
                alpha = int(base_alpha * var * rhythm * (1.0 + FLOOR_BEAT_FLASH * flash))
                if alpha <= 1:
                    continue
                fill = QColor(FX_FLOOR)
                fill.setAlpha(alpha)
                painter.setBrush(fill)
                u0 = col / cols - 0.5
                u1 = (col + 1) / cols - 0.5
                poly = QPolygonF(
                    [
                        QPointF(w / 2 + u0 * spread * s0, y0),
                        QPointF(w / 2 + u1 * spread * s0, y0),
                        QPointF(w / 2 + u1 * spread * s1, y1),
                        QPointF(w / 2 + u0 * spread * s1, y1),
                    ]
                )
                painter.drawPolygon(poly)
        painter.restore()

    def _draw_hud(self, painter: QPainter, w: float, h: float) -> None:
        """Small tech-style corner brackets, labels and cross markers."""
        t = self._fx_time
        flick_a = 0.72 + 0.28 * math.sin(t * 2.1)
        flick_b = 0.72 + 0.28 * math.sin(t * 1.3 + 1.7)

        def navy(alpha: float) -> QColor:
            c = QColor(FX_NAVY)
            c.setAlpha(int(alpha))
            return c

        # Bold letterspaced title, with a tiny caption line under it.
        title_font = ui_font(15)
        title_font.setWeight(QFont.Bold)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        caption_font = ui_font(7)
        caption_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
        label_font = ui_font(9)
        label_font.setWeight(HEADING_WEIGHT)
        label_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        tiny_font = ui_font(6)
        tiny_font.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)

        pen = QPen(navy(70 * flick_a))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Corner brackets.
        m = 14
        size = 22
        for cx, cy, dx, dy in (
            (m, m, 1, 1),
            (w - m, m, -1, 1),
            (m, h - m, 1, -1),
            (w - m, h - m, -1, -1),
        ):
            painter.drawLine(QPointF(cx, cy + dy * size), QPointF(cx, cy))
            painter.drawLine(QPointF(cx, cy), QPointF(cx + dx * size, cy))

        # Top-left block: the page title, sized to read as a real heading.
        painter.setFont(title_font)
        painter.setPen(navy(205 * flick_a))
        title_text = "SYSTEM MONITOR"
        painter.drawText(QPointF(m + 10, m + 32), title_text)
        title_w = QFontMetrics(title_font).horizontalAdvance(title_text)
        # Small green accent block leading the caption.
        accent = QColor(118, 185, 0)
        accent.setAlpha(int(190 * flick_a))
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRect(QRectF(m + 11, m + 40, 12, 2))
        painter.setPen(navy(120 * flick_b))
        painter.setFont(caption_font)
        painter.drawText(QPointF(m + 27, m + 43), "AFTERFRAME // REALTIME STATUS")
        painter.setPen(QPen(navy(46 * flick_a), 1))
        painter.drawLine(QPointF(m + 10, m + 51), QPointF(m + 10 + title_w, m + 51))

        # Top-right label block, aligned with the new title baseline.
        painter.setFont(label_font)
        painter.setPen(navy(150 * flick_b))
        painter.drawText(
            QPointF(w - m - 128, m + 32), f"{APP_VERSION.upper()} // ACTIVE"
        )
        painter.setFont(tiny_font)
        painter.setPen(navy(95 * flick_a))
        painter.drawText(QPointF(w - m - 128, m + 44), "MONITOR LINK ─ STABLE")

        # Bottom-left / bottom-right micro labels.
        painter.setFont(tiny_font)
        painter.setPen(navy(85 * flick_b))
        painter.drawText(QPointF(m + 8, h - m - 8), "DIMENSION // S-STATUS")
        painter.setPen(navy(85 * flick_a))
        painter.drawText(QPointF(w - m - 96, h - m - 8), "ENGINE // 60FPS")

        # Cross markers at fixed spots.
        for fx, fy in ((0.30, 0.10), (0.86, 0.30), (0.12, 0.60)):
            cx = w * fx
            cy = h * fy
            painter.setPen(QPen(navy(80 * flick_b), 1))
            painter.drawLine(QPointF(cx - 4, cy), QPointF(cx + 4, cy))
            painter.drawLine(QPointF(cx, cy - 4), QPointF(cx, cy + 4))

    # ------------------------------------------------------------------
    # Dashboard logic
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        # The HUD decorations painted in paintEvent carry the page title
        # ("SYSTEM MONITOR"); clear that block before the subtitle.
        layout.addSpacing(58)

        sub = QLabel("实时系统状态 · 点击卡片查看详情")
        sub.setStyleSheet(
            "color: rgba(30, 42, 62, 0.52); font-size: 13px; background: transparent;"
        )
        layout.addWidget(sub)

        layout.addSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(16)

        self._cpu_card = MetricCard("CPU 使用率")
        self._cpu_card.clicked.connect(lambda: self._show_detail("cpu"))

        self._mem_card = MetricCard("内存 使用率")
        self._mem_card.clicked.connect(lambda: self._show_detail("memory"))

        self._disk_card = MetricCard("磁盘 使用率")
        self._disk_card.clicked.connect(lambda: self._show_detail("disk"))

        self._net_card = MetricCard("网络")
        self._net_card.clicked.connect(lambda: self._show_detail("network"))

        grid.addWidget(self._cpu_card, 0, 0)
        grid.addWidget(self._mem_card, 0, 1)
        grid.addWidget(self._disk_card, 1, 0)
        grid.addWidget(self._net_card, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()

        self._detail = DetailPanel(self)
        self._detail.hide()
        self._detail.closed.connect(self._hide_detail)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._active_detail is not None and self._detail.isVisible():
            # Keep the panel in its expanded geometry when the dashboard resizes.
            self._detail.setGeometry(self._expanded_geometry())

    def _expanded_geometry(self) -> QRect:
        """Return the target geometry for an expanded detail panel."""
        margin = int(min(self.width(), self.height()) * 0.08)
        return QRect(
            margin,
            margin,
            self.width() - margin * 2,
            self.height() - margin * 2,
        )

    def _card_geometry(self, card: MetricCard) -> QRect:
        """Return the geometry of a card in dashboard coordinates."""
        return QRect(card.mapTo(self, QPoint(0, 0)), card.size())

    def _show_detail(self, key: str) -> None:
        if self._active_detail == key:
            return

        card_map: Dict[str, MetricCard] = {
            "cpu": self._cpu_card,
            "memory": self._mem_card,
            "disk": self._disk_card,
            "network": self._net_card,
        }
        card = card_map[key]

        if self._active_detail is not None:
            # Switching between open details: just swap content in place.
            self._active_detail = key
            self._refresh_detail_content(key)
            return

        self._active_detail = key
        start_geo = self._card_geometry(card)
        end_geo = self._expanded_geometry()

        self._refresh_detail_content(key)
        self._detail.setGeometry(start_geo)
        self._detail.show()
        self._detail.raise_()

        self._open_anim = QPropertyAnimation(self._detail, b"geometry")
        self._open_anim.setDuration(450)
        self._open_anim.setStartValue(start_geo)
        self._open_anim.setEndValue(end_geo)
        self._open_anim.setEasingCurve(QEasingCurve.OutBack)
        self._open_anim.start()

    def _hide_detail(self) -> None:
        if self._active_detail is None:
            return

        card_map: Dict[str, MetricCard] = {
            "cpu": self._cpu_card,
            "memory": self._mem_card,
            "disk": self._disk_card,
            "network": self._net_card,
        }
        card = card_map[self._active_detail]
        end_geo = self._card_geometry(card)
        start_geo = self._detail.geometry()

        self._close_anim = QPropertyAnimation(self._detail, b"geometry")
        self._close_anim.setDuration(350)
        self._close_anim.setStartValue(start_geo)
        self._close_anim.setEndValue(end_geo)
        self._close_anim.setEasingCurve(QEasingCurve.InBack)
        self._close_anim.finished.connect(self._on_detail_hidden)
        self._close_anim.start()

    def _on_detail_hidden(self) -> None:
        self._detail.hide()
        self._active_detail = None

    def _refresh_detail_content(self, key: str) -> None:
        self._detail.clear()

        if key == "cpu":
            self._detail.set_title("CPU 详情")
            freq = psutil.cpu_freq()
            if freq:
                self._detail.add_row("当前频率", f"{freq.current:.0f} MHz")
                if freq.max:
                    self._detail.add_row("最大频率", f"{freq.max:.0f} MHz")
            self._detail.add_row("物理核心", str(psutil.cpu_count(logical=False)))
            self._detail.add_row("逻辑核心", str(psutil.cpu_count(logical=True)))
            per_cpu = psutil.cpu_percent(interval=None, percpu=True)
            for i, p in enumerate(per_cpu):
                self._detail.add_bar(f"核心 {i + 1}", p)

        elif key == "memory":
            self._detail.set_title("内存 详情")
            mem = psutil.virtual_memory()
            self._detail.add_row("总计", f"{self._bytes_to_gb(mem.total)} GB")
            self._detail.add_row("已用", f"{self._bytes_to_gb(mem.used)} GB")
            self._detail.add_row("可用", f"{self._bytes_to_gb(mem.available)} GB")
            self._detail.add_row("使用率", f"{mem.percent:.1f}%")
            swap = psutil.swap_memory()
            self._detail.add_row("Swap 总计", f"{self._bytes_to_gb(swap.total)} GB")
            self._detail.add_row("Swap 已用", f"{self._bytes_to_gb(swap.used)} GB")
            self._detail.add_bar("内存使用", mem.percent)

        elif key == "disk":
            self._detail.set_title("磁盘 详情")
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    self._detail.add_bar(
                        f"{part.device} ({part.mountpoint})", usage.percent
                    )
                    self._detail.add_row(
                        "已用 / 总计",
                        f"{self._bytes_to_gb(usage.used)} / {self._bytes_to_gb(usage.total)} GB",
                    )
                except PermissionError:
                    continue

        elif key == "network":
            self._detail.set_title("网络 详情")
            net = psutil.net_io_counters()
            self._detail.add_row("总发送", self._bytes_to_human(net.bytes_sent))
            self._detail.add_row("总接收", self._bytes_to_human(net.bytes_recv))
            self._detail.add_row("发送包", self._bytes_to_human(net.packets_sent))
            self._detail.add_row("接收包", self._bytes_to_human(net.packets_recv))
            if self._last_net_time is not None:
                dt = time.time() - self._last_net_time
                sent_speed = (net.bytes_sent - self._last_net_sent) / max(dt, 0.001)
                recv_speed = (net.bytes_recv - self._last_net_recv) / max(dt, 0.001)
                self._detail.add_row("上传速度", f"{self._bytes_to_human(sent_speed)}/s")
                self._detail.add_row("下载速度", f"{self._bytes_to_human(recv_speed)}/s")

    def _update(self) -> None:
        # CPU
        cpu = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        self._cpu_card.set_value(cpu, f"{cpu_count} 逻辑处理器")

        # Memory
        mem = psutil.virtual_memory()
        self._mem_card.set_value(
            mem.percent,
            f"已用 {self._bytes_to_gb(mem.used)} / 总计 {self._bytes_to_gb(mem.total)} GB",
        )

        # Disk
        disk = psutil.disk_usage("/")
        self._disk_card.set_value(
            disk.percent,
            f"已用 {self._bytes_to_gb(disk.used)} / 总计 {self._bytes_to_gb(disk.total)} GB",
        )

        # Network speed
        net = psutil.net_io_counters()
        now = time.time()
        if self._last_net_time is not None:
            dt = now - self._last_net_time
            sent_speed = (net.bytes_sent - self._last_net_sent) / dt
            recv_speed = (net.bytes_recv - self._last_net_recv) / dt
            self._net_card.set_custom_value(
                f"↑{self._bytes_to_human(sent_speed)}/s",
                f"↓ {self._bytes_to_human(recv_speed)}/s",
            )
            if self._active_detail == "network":
                self._refresh_detail_content("network")
        else:
            self._net_card.set_custom_value("--", "网络活动")

        self._last_net_time = now
        self._last_net_sent = net.bytes_sent
        self._last_net_recv = net.bytes_recv

        if self._active_detail == "cpu":
            self._refresh_detail_content("cpu")
        elif self._active_detail == "memory":
            self._refresh_detail_content("memory")
        elif self._active_detail == "disk":
            self._refresh_detail_content("disk")

    @staticmethod
    def _bytes_to_gb(b: int) -> float:
        return round(b / (1024 ** 3), 1)

    @staticmethod
    def _bytes_to_human(b: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"
