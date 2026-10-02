"""Per-page chrome themes for the sidebar and the title bar.

The pages have very different moods - the system dashboard is bright white
while the music page is dark - so the chrome around them adopts a matching
palette and cross-fades smoothly when the user switches pages.

Each theme carries two colours for the chrome's own background:

* `chrome_base` is painted UNDER the wash. It is what the chrome looks like when
  the compositor's blur material is not available, and what the minimize/close
  pre-roll fades to (`chrome_flat`). It is deliberately per-theme rather than the
  window's dark BACKGROUND_COLOR: with a thin wash the dark base would drag a
  bright page's chrome down to mid grey, and those pages must stay light.
* `chrome_bg` is the wash painted over the material (by the widgets themselves).
  Its alpha decides how much blur shows through -- see the measurement notes on
  each theme below. The alphas written here are the 标准 frost level; picking a
  different level in the settings replaces the alpha (see `FROSTED_LEVELS`).
"""

from PySide6.QtCore import QEasingCurve, QObject, QVariantAnimation
from PySide6.QtGui import QColor

from .constants import BACKGROUND_COLOR, DEFAULT_FROSTED_LEVEL, frosted_wash_alpha


def rgba(color: QColor) -> str:
    """Format a QColor as a Qt stylesheet rgba() string."""
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


def _theme(
    chrome_base: QColor,
    chrome_bg: QColor,
    chrome_border: QColor,
    icon_idle: QColor,
    icon_hover: QColor,
    text: QColor,
    control_idle: QColor,
    control_hover_bg: QColor,
    control_hover_text: QColor,
) -> dict:
    return {
        "chrome_base": chrome_base,
        "chrome_bg": chrome_bg,
        "chrome_border": chrome_border,
        "icon_idle": icon_idle,
        "icon_hover": icon_hover,
        "icon_active": QColor(118, 185, 0),  # brand green in both themes
        "text": text,
        "control_idle": control_idle,
        "control_hover_bg": control_hover_bg,
        "control_hover_text": control_hover_text,
    }


# Indexed by page: 0 = system dashboard (bright), 1 = music player (grey/dark),
# 2 = settings (bright, matching its own light page).
#
# The wash alphas are the frosted-glass knob: the blur showing through is
# proportional to (1 - alpha/255), measured against a checkered backdrop as a
# luma sigma of 51.4 for the music page's alpha 26. The bright pages sit at 180 --
# a clear frost (sigma ~15) that still leaves the wash dominant, so their dark
# text keeps its contrast over any wallpaper: even over pure black the chrome
# lands around luma 174, where the title text measures ~5.5:1.
PAGE_THEMES = [
    _theme(
        chrome_base=QColor(247, 249, 252),
        chrome_bg=QColor(247, 249, 252, 180),
        chrome_border=QColor(30, 42, 62, 28),
        icon_idle=QColor(30, 42, 62, 115),
        icon_hover=QColor(30, 42, 62, 225),
        text=QColor(30, 42, 62, 235),
        control_idle=QColor(30, 42, 62, 150),
        control_hover_bg=QColor(30, 42, 62, 24),
        control_hover_text=QColor(30, 42, 62, 255),
    ),
    _theme(
        chrome_base=QColor(*BACKGROUND_COLOR),
        chrome_bg=QColor(255, 255, 255, 26),
        chrome_border=QColor(255, 255, 255, 22),
        icon_idle=QColor(255, 255, 255, 115),
        icon_hover=QColor(255, 255, 255, 230),
        text=QColor(255, 255, 255, 220),
        control_idle=QColor(255, 255, 255, 180),
        control_hover_bg=QColor(255, 255, 255, 28),
        control_hover_text=QColor(255, 255, 255, 255),
    ),
    # Settings: a touch cooler than the dashboard so the page reads as its own
    # place while keeping dark text on a light chrome.
    _theme(
        chrome_base=QColor(242, 246, 252),
        chrome_bg=QColor(242, 246, 252, 180),
        chrome_border=QColor(30, 42, 62, 30),
        icon_idle=QColor(30, 42, 62, 115),
        icon_hover=QColor(30, 42, 62, 225),
        text=QColor(30, 42, 62, 235),
        control_idle=QColor(30, 42, 62, 150),
        control_hover_bg=QColor(30, 42, 62, 24),
        control_hover_text=QColor(30, 42, 62, 255),
    ),
]


def theme_for_page(index: int, level: int = DEFAULT_FROSTED_LEVEL) -> dict:
    """Return a copy of the theme for *index*, washed at the frosted *level*.

    The alphas in `PAGE_THEMES` are the 标准 level; any other level replaces the
    wash's alpha. The opaque level (`None`) makes the wash fully TRANSPARENT
    rather than opaque, so the chrome is exactly `chrome_base` -- an opaque white
    wash would paint the music page's dark chrome white, because the wash is the
    colour the strips are filled with when the material is not in use.
    """
    known = 0 <= index < len(PAGE_THEMES)
    source = PAGE_THEMES[index] if known else PAGE_THEMES[-1]
    theme = {key: QColor(value) for key, value in source.items()}
    wash = theme["chrome_bg"]
    alpha = frosted_wash_alpha(index if known else len(PAGE_THEMES) - 1, level)
    wash.setAlpha(0 if alpha is None else alpha)
    theme["chrome_bg"] = wash
    return theme


def interpolate_theme(start: dict, end: dict, t: float) -> dict:
    """Blend two themes by *t* in 0..1 (includes alpha)."""
    t = max(0.0, min(1.0, float(t)))
    blended = {}
    for key, end_color in end.items():
        start_color = start.get(key)
        if start_color is None:
            blended[key] = QColor(end_color)
            continue
        blended[key] = QColor(
            int(start_color.red() + (end_color.red() - start_color.red()) * t),
            int(start_color.green() + (end_color.green() - start_color.green()) * t),
            int(start_color.blue() + (end_color.blue() - start_color.blue()) * t),
            int(start_color.alpha() + (end_color.alpha() - start_color.alpha()) * t),
        )
    return blended


class ThemeAnimator(QObject):
    """Cross-fades a widget's palette from its current theme to a new one."""

    def __init__(self, apply_fn, parent: QObject = None) -> None:
        super().__init__(parent)
        self._apply = apply_fn
        self._current: dict | None = None
        self._from: dict | None = None
        self._to: dict | None = None

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._on_value)

    def current(self) -> dict | None:
        return self._current

    def to(self, theme: dict, animate: bool = True, duration: int = 420) -> None:
        """Apply *theme*, easing from the current colors unless disabled."""
        self._anim.stop()
        if not animate or self._current is None:
            self._current = {key: QColor(value) for key, value in theme.items()}
            self._apply(self._current)
            return

        # Interrupting a running fade starts from the blended colors.
        self._from = {key: QColor(value) for key, value in self._current.items()}
        self._to = {key: QColor(value) for key, value in theme.items()}
        self._anim.setDuration(duration)
        self._anim.start()

    def _on_value(self, value) -> None:
        if self._from is None or self._to is None:
            return
        self._current = interpolate_theme(self._from, self._to, float(value))
        self._apply(self._current)
