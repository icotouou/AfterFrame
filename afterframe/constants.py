import sys

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QFont

from . import __version__

# Intro window geometry
WINDOW_WIDTH = 300
WINDOW_HEIGHT = 110
INITIAL_SIZE = 1

# Main window geometry
MAIN_WINDOW_WIDTH = 960
MAIN_WINDOW_HEIGHT = 600
# Smallest the window may be. Measured from the real layouts: the dashboard
# needs 488x517 and the settings page 520x498 inside the page stack, plus the
# 72 px sidebar and 36 px title bar -- i.e. ~592x553. Rounded up so no page is
# ever clipped or squashed.
MAIN_WINDOW_MIN_WIDTH = 600
MAIN_WINDOW_MIN_HEIGHT = 560

# UI dimensions
TITLE_BAR_HEIGHT = 36

# Window corners (0 = sharp corners)
WINDOW_CORNER_RADIUS = 0

# Drag-resize grip, in logical pixels. RESIZE_CORNER is deliberately larger
# than RESIZE_BORDER so a corner is easy to catch for diagonal resizing.
RESIZE_BORDER = 10
RESIZE_CORNER = 24

# Springy settle after releasing a resize drag ("Q弹" bounce). Set to False to
# snap straight to the released size. The leap is capped at OVERSHOOT pixels and
# scaled by RESIZE_VELOCITY_GAIN per px/ms of release speed, so a brisk drag
# bounces clearly while a careful one barely moves. Keep the gain low enough
# that ordinary drag speeds stay below the cap, otherwise every release bounces
# by the same amount.
MAIN_WINDOW_RESIZE_BOUNCE = True
# Release kick in px per frame, scaled from the drag's own speed (px/ms), so a
# brisk drag bounces further than a careful one. Capped by the value above.
MAIN_WINDOW_RESIZE_OVERSHOOT = 26.0
RESIZE_RELEASE_VELOCITY_GAIN = 5.0
# Time constant (ms) for smoothing the drag velocity, and the age (ms) past
# which a pointer sample is too stale to say anything about release speed.
RESIZE_VELOCITY_TAU_MS = 60.0
RESIZE_VELOCITY_STALE_MS = 600

# Dragging an edge inward past the minimum size does not stop dead: the window
# is squeezed by a diminishing fraction of the extra distance, like a rubber
# band approaching its limit, then springs back to the minimum on release.
# SOFTNESS is how many px past the minimum it takes to reach half the squeeze;
# larger = softer for longer. POWER <1 makes the first part of the travel give
# more readily; MAX is the asymptote the squeeze approaches (never a wall).
MAIN_WINDOW_RESIZE_SQUEEZE = True
RESIZE_SQUEEZE_SOFTNESS = 170.0
RESIZE_SQUEEZE_POWER = 0.88
RESIZE_SQUEEZE_MAX = 130.0

# Outward kick applied when a squeezed window is released, as a fraction of the
# distance it has to spring open, capped so the first frame does not leap.
RESIZE_OPEN_VELOCITY_GAIN = 0.18
RESIZE_OPEN_VELOCITY_MAX = 15.0

# Spring constants used by the resize release spring only. Light damping is what
# makes it read as jelly: at the drag spring's 0.55 the window overshoots once
# and stops, which feels crisp rather than wobbly.
RESIZE_SPRING_STIFFNESS = 0.15
RESIZE_SPRING_DAMPING = 0.28

# Animation durations (ms)
EXPAND_DURATION = 650
FLASH_DURATION = 1500
FLASH_COUNT = 4
MOVE_DURATION = 1400
TRANSITION_TO_MAIN_DURATION = 500

# Easing curves
EXPAND_EASING = QEasingCurve.OutBack
MOVE_EASING = QEasingCurve.InOutCubic
TRANSITION_TO_MAIN_EASING = QEasingCurve.OutQuint

# Visual style
BACKGROUND_COLOR = (21, 21, 21)
# The window's own base, painted once behind every child. It used to be 235/255,
# i.e. the one place in the window that was painted with alpha -- measured on
# screen (white vs black backing behind the window, compositor capture, controls
# proving the probe could see alpha), that base was already fully covered by the
# children, so it leaked nothing; 255 makes it a guarantee instead of a
# coincidence. Only used here (window.py's paintEvent) -- nothing else reads it.
BACKGROUND_ALPHA = 255
# Frosted chrome: the title bar and sidebar are painted with the theme's
# translucent wash, so with this material behind them the compositor blurs what
# is behind the window -- and only there, the page area keeps its own opaque
# base. AccentState 4 is acrylic. AccentFlags must stay != 2: measured on screen
# (compositor capture, controls proving the probe can see blur and alpha), the
# flag-2 material keeps 4% of a large feature's contrast -- the window behind is
# erased -- while 0/1/4 keep 82% and are indistinguishable from each other.
FROSTED_CHROME_STATE = 4
FROSTED_CHROME_FLAGS = 0
FROSTED_CHROME_TINT = 0x00000000  # ABGR; 0 leaves the tint to the theme's wash

# How frosted the chrome is, from the left of the settings control (opaque) to
# the right (very see-through). Each entry is (label, alphas) and the alphas are
# per page -- (dashboard, music, settings) -- because the pages are not alike:
# the bright pages need a thick wash to keep their dark text readable on a dark
# wallpaper, while the music page is dark and already starts from a very thin
# one. `None` means "no compositor material at all": the chrome is painted with
# the theme's own base colour, which is also the fallback when this machine
# cannot do the material.
# The 标准 entry repeats the themes' built-in alphas, so the control's default
# position is pixel-identical to how the window looked before it existed.
FROSTED_LEVELS = (
    ("不透明", (None, None, None)),
    ("微透", (235, 96, 235)),
    ("标准", (180, 26, 180)),
    ("通透", (120, 16, 120)),
)
DEFAULT_FROSTED_LEVEL = 2


def frosted_wash_alpha(page_index: int, level: int) -> "int | None":
    """Wash alpha for *page_index* at *level*; None = no material on that page."""
    levels = FROSTED_LEVELS
    alphas = levels[max(0, min(len(levels) - 1, int(level)))][1]
    if not 0 <= page_index < len(alphas):
        page_index = len(alphas) - 1
    return alphas[page_index]

BAR_COLOR = (118, 185, 0)  # NVIDIA green #76B900
TEXT_COLOR = (255, 255, 255)
TEXT_SECONDARY_COLOR = (180, 180, 180)
BORDER_COLOR = (60, 60, 60)
CLOSE_HOVER_COLOR = (232, 17, 35)

# Bar dimensions
BAR_WIDTH = 10
BAR_HEIGHT = WINDOW_HEIGHT
BAR_LEFT_PADDING = 28

# Trail
TRAIL_MAX_AGE_MS = 350
TRAIL_SAMPLE_INTERVAL_MS = 12
TRAIL_COUNT = 28

# Text
APP_NAME = "AfterFrame"

# Derived from the package version rather than written again here.
#
# The two used to be independent literals -- __version__ said "0.1.0" while this said
# "v1.0" -- and nothing read the former, so the interface quietly disagreed with the
# package metadata and no test or check could notice. One source, one display form: bump
# __version__ in afterframe/__init__.py and the corner of every page follows.
#
# The "v" lives here because it is presentation: the interface puts it through .upper()
# on the way out.
APP_VERSION = "v" + __version__


def resource_path(name: str):
    """Locate a bundled data file in both a source checkout and a frozen build.

    A packaged build does not keep the source layout, so a plain relative path works while
    developing and then fails in the build -- the one place that is awkward to debug. The
    frozen layouts differ per tool and are not something to guess at, so this tries the
    known locations in order rather than branching on tool-specific globals:

      * beside the executable          -- Nuitka onefile extracts its data next to it
      * PyInstaller's unpack directory -- `sys._MEIPASS`, when it is set
      * the repository root            -- running from source

    Returns a Path; callers decide what to do when the file is not there.
    """
    from pathlib import Path

    candidates = [Path(sys.executable).resolve().parent / name]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / name)
    candidates.append(Path(__file__).resolve().parent.parent / name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


# One interface font everywhere: a sans-serif (黑体) that covers both Latin and
# CJK, so titles, lyrics and lists stay easy to read.
UI_FONT_FAMILY = "Microsoft YaHei UI"
UI_FONT_STACK = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "SimHei",
    "Segoe UI",
    "Arial",
    # Symbol-capable faces, last: a lyric line like
    #     aaaa~(˶˃ ᵕ ˂˶) .ᐟ.ᐟ        (U+02F6 U+02C3 U+1D55 U+02C2 U+141F)
    # has glyphs none of the families above carry. Without a real fallback Qt
    # reaches for the bitmap face "Fixedsys", fails, and repeats that failure --
    # with a stderr write -- on EVERY repaint. The lyrics repaint ~60x/s, so the
    # UI thread spent its time in DirectWrite and in the console, the audio pump
    # (a 16 ms timer on that same thread) missed its deadlines, and the music
    # stuttered for exactly as long as the line was on screen. Measured with that
    # line: 1 DirectWrite warning per render before, 0 after, and normal text comes
    # out pixel-identical (the extra families are only consulted for glyphs the
    # earlier ones lack).
    "Segoe UI Symbol",
    "Segoe UI Emoji",
)
# Glyph icons (◆ ◈ ✦ ⚙ − ✕) need a symbol-capable face.
ICON_FONT_FAMILY = "Segoe UI Symbol"
TEXT_FONT_FAMILY = UI_FONT_FAMILY
TEXT_FONT_SIZE = 26
TEXT_Y_OFFSET = 0.5  # fraction of window height
TEXT_REVEAL_BAND = 8  # pixels for sharp per-letter reveal

# The family list `ui_font` actually builds, kept separate from UI_FONT_STACK so it
# can be rebuilt once the font database is up.
#
# Microsoft YaHei ships only three weights (msyh.ttc regular, msyhbd.ttc bold,
# msyhl.ttc light), so there is nothing between regular and bold: a request for
# Medium or DemiBold quietly lands back on regular. Noto Sans SC is installed here
# as a VARIABLE font (NotoSansSC-VF.ttf), whose weight axis can supply the
# intermediate weights YaHei cannot -- which is what an interface that reads "too
# thin" but should not jump straight to bold actually needs.
#
# It goes FIRST and the rest of UI_FONT_STACK stays behind it: the symbol-capable
# families at the end of that stack are load-bearing (see the note above them).
_ACTIVE_FONT_STACK: list = list(UI_FONT_STACK)


def preferred_font_family() -> str:
    """Noto Sans SC when this machine has it, else the default UI family.

    Resolved at runtime because the answer comes from the font database, which is
    only available once a QGuiApplication exists.
    """
    try:
        from PySide6.QtGui import QFontDatabase

        if "Noto Sans SC" in QFontDatabase.families():
            return "Noto Sans SC"
        # A missing font database just means the preferred face cannot be
        # checked for; the default family is a fine answer.
    except Exception:
        pass
    return UI_FONT_FAMILY


def use_preferred_font() -> str:
    """Point the whole interface at the preferred family. Returns the family used.

    Also clears the prototype cache: `ui_font` caches one prototype per (size,
    weight), and every cached entry was built with the previous family, so leaving
    them would keep the old face on screen for exactly the sizes rendered before
    the switch.
    """
    global _ACTIVE_FONT_STACK
    family = preferred_font_family()
    if family == UI_FONT_FAMILY:
        stack = list(UI_FONT_STACK)
    else:
        # Preferred face first, then the original stack minus a duplicate of it.
        stack = [family] + [f for f in UI_FONT_STACK if f != family]
    if stack != _ACTIVE_FONT_STACK:
        _ACTIVE_FONT_STACK = stack
        _UI_FONT_PROTOTYPES.clear()
    return family


def active_font_stack() -> tuple:
    """The family list currently in force, for widgets that set it themselves."""
    return tuple(_ACTIVE_FONT_STACK)


def small_ui_font(size: int = 9, weight=None):
    """Interface font for SMALL text, on the face that stays legible when it is small.

    Noto Sans SC is the preferred face for headings and menus here -- it renders the
    Latin and the icon glyphs noticeably better than Microsoft YaHei, which is why the
    menus were reported as looking cleaner. At the sizes dense Chinese text is set in,
    though, it draws thinner strokes than YaHei, and thin horizontal strokes are what
    makes a character read as if a corner were missing.

    Measured on the settings page's own strings, solid ink pixels, same size each:

        启用          9pt   Noto 302  YaHei 348
        通透         11pt   Noto 591  YaHei 646
        标准         11pt   Noto 497  YaHei 553
        设置播放器页面的歌曲来源 9pt   Noto 2087 YaHei 2374
        磨砂玻璃外壳    11pt   Noto 1618 YaHei 1711
        total                    5641       6178   (+9.5%)

    The other levers were tried and do not work at these sizes: a heavier weight
    renders byte-identical to regular, and the hinting preference is ignored by the
    Windows backend (a whole-page render with it on and off came out pixel-identical).
    The face is the only lever left, so small text uses it.

    Note this deliberately does NOT change the application font: the music menu is a
    widget with `setFont(ui_font())`, and it is one of the places the preferred face
    is wanted.
    """
    family = UI_FONT_FAMILY
    try:
        from PySide6.QtGui import QFontDatabase

        for candidate in (UI_FONT_FAMILY, "Microsoft YaHei", "SimHei"):
            if candidate in QFontDatabase.families():
                family = candidate
                break
        # Same: the fallback family list is only a preference order.
    except Exception:
        pass
    font = QFont(family, size)
    try:
        # Keep the symbol fallbacks: lyrics and icons rely on them (see UI_FONT_STACK).
        font.setFamilies([family] + [f for f in UI_FONT_STACK if f != family])
        # Qt without setFamilies (older builds) keeps the single family
        # set above, which is still readable.
    except Exception:
        pass
    if weight is not None:
        font.setWeight(weight)
    return font


# Which weight a heading should ask for.
#
# Do NOT use QFont.DemiBold for headings on the variable face. Measured with Noto
# Sans SC at 18pt, the stem width each constant actually renders (device pixels):
#
#     QFont.Light   (300) ->  3.99
#     QFont.Normal  (400) ->  6.14
#     QFont.Medium  (500) ->  7.58   <- the step headings want
#     QFont.DemiBold(600) ->  4.15   <- THINNER THAN LIGHT
#     QFont.Bold    (700) ->  9.23
#
# Qt quantises a requested weight onto the variable face's axis, and 600 lands on a
# far lighter instance than 500 does: a heading asking for DemiBold comes out thinner
# than the regular text beside it. That is invisible on small menu text and obvious
# on a heading, which is exactly how it was reported. Medium sits on the real
# intermediate step (460), about 20% heavier than regular.
HEADING_WEIGHT = QFont.Medium


# One tooltip look for the whole application.
#
# Qt resolves a QToolTip rule from the widget showing the tip, or from its parent,
# or from the application -- all three were measured to work. Without any of them it
# falls back to the palette's BLACK text, which is unreadable on this dark tip
# background; that is why every widget with a tooltip used to need its own copy.
# Defined once, at application level, so a widget's own setStyleSheet cannot drop
# it and no new row has to remember it.
TOOLTIP_STYLE = """
    QToolTip {
        color: rgba(255, 255, 255, 0.9);
        background-color: rgba(32, 34, 40, 240);
        border: 1px solid rgba(255, 255, 255, 40);
        border-radius: 6px;
        /* No `padding` on purpose. Qt's tip label is a static, reused widget,
           and a stylesheet padding is applied TWICE on a freshly created one and
           NOT AT ALL once it is reused: measured heights are 28 px for the first
           tip of a process (and for any tip after the label was torn down by
           hovering it) against 20 px for the rest -- which shows up as the first
           tip being visibly one size bigger than its own text. Border and radius
           do not have that asymmetry, and the native metrics already leave a
           margin. */
    }
"""

# Marquee for the track title / artist+album lines under the cover. A line only
# scrolls when it is wider than its column; it rests at the head, slides to the
# tail, rests again, then snaps back to the start.
INFO_SCROLL_SPEED_PX_S = 26.0
INFO_SCROLL_HEAD_PAUSE_MS = 900.0
INFO_SCROLL_TAIL_PAUSE_MS = 1100.0

# Page tint: the veil the music page draws over its whole background so the UI
# drawn straight on top stays readable. It was 168/255 of (16, 18, 22), i.e. 66%
# of a near-black -- measured, that pulled a colourful backdrop down to 70% of its
# brightness and towards the tint's own luma (~18), which is what made the page
# read as "dark overall" (most obvious once the backdrop had colour). At 138 the
# tint still took 34 luma (35%) off the page, so its COLOUR was lightened to
# (40,43,50): measured, the page mean goes 61.9 -> 71.8 luma and the median
# background 54.6 -> 65.6, at a cost of text contrast (proxy 2.3:1 -> 1.9:1).
# Lightening the colour rather than lowering the alpha keeps the wash flat: a lower
# alpha instead lets more of the artwork's own texture show behind the text.
PAGE_TINT_COLOR = (40, 43, 50)
PAGE_TINT_ALPHA = 138

# Transport-button press feedback. A click presses the glyph downward and
# squashes it vertically, then it springs back up with a couple of soft wobbles,
# like a fingertip pressing into jelly. Light damping keeps the wobble visible.
BTN_PRESS_KICK = 7.0
BTN_PRESS_STIFFNESS = 0.16
BTN_PRESS_DAMPING = 0.20

# "音乐色彩" background: a hazy field of the cover's own palette, with two soft
# swirls and a school of drops melted into it, and a frosted sheet in front of all
# of it so the UI stays readable. There is no cover picture anywhere: it is
# deliberately the cover's *colours* only, never the picture, and the swirls and
# drops blend into that haze rather than sitting on top of it.
#
# The field is drawn TINY and smoothly upscaled instead of being blurred: that
# upscale is the whole filter, which is why it can be rebuilt every frame (and
# therefore drift) where a real blur pass had to be cached. COLOR_BG_BLUR_DIVISOR
# says how much softer the frosted sheet in front is than the field itself.
COLOR_BG_BLUR_DIVISOR = 45  # the frosted sheet in front
# The palette mist itself: how many blobs, how strong, how far they wander and how
# fast. Built at 1/COLOR_MIST_DIVISOR of the page and smoothly upscaled -- that
# upscale IS the blur, so unlike a real blur pass this field can be rebuilt every
# frame and genuinely drift.
COLOR_MIST_DIVISOR = 12
COLOR_MIST_BLOBS = 5
# Blob radius as a fraction of the page's longer side. Measured against the blurred
# cover this backdrop replaces: at 0.34 the five blobs left enough dark base showing
# to land at 65% of its brightness and 60% of its channel spread.
COLOR_MIST_BLOB_SIZE = 0.36
COLOR_MIST_BLOB_ALPHA = 255
# The blobs are opaque at their centres on purpose: the field replaces a *cover*,
# and the backdrop it sits on was measured at luma 61-146 with a channel spread of
# 30-62. At alpha 165 the mist came out at half that brightness and 40% of the
# spread, i.e. grey. Overlaps still blend because each blob fades to zero alpha
# towards its rim.
COLOR_MIST_DRIFT_X = 0.012  # sideways wander, fraction of the page width per second
COLOR_MIST_DRIFT_Y = 0.008
COLOR_MIST_DRIFT_RAD_PER_S = 0.16  # the mist's own clock, in radians per second
COLOR_MIST_BREATHE = 0.10  # blob radius breathing, fraction of its own radius
# The frosted sheet: how opaque it is, and how far it darkens the cover behind it.
# Tuned by rendering with a real cover: at 138/84 the sheet washed the artwork and
# the shapes out completely; at 102/66 the whole backdrop read as too see-through,
# so it sits in between -- body from the blur itself, not from burying the colour.
COLOR_FROST_ALPHA = 20
COLOR_FROST_DARKEN = 10
# Cover backdrop: darkened by this alpha before anything else is drawn on it.
COLOR_BACKDROP_DARKEN = 48
# The two glass slabs. They are ANCHORED: the drawing has them cut by the frame
# off two opposite corners, and they never translate -- they only turn, slowly, in
# place. Geometry (centre, radius, tilt) is measured off that drawing (1536x960,
# the page's own 1.6 aspect) by thresholding it and least-squares fitting the
# hand-drawn arcs: see _COLOR_SLABS in toy_page.py for the numbers.
#
# The two glass slabs melted into the haze: what is left of them is one soft oval
# patch of denser fog each, turning slowly in place. With no rim to give the shape
# away the turn is carried by the oval's tilt (a circle turning looks static), and
# the "density" is just a faint white lift over the mist -- the pages's own mist
# colours stay in charge of the hue.
COLOR_SHAPE_SPIN_DEG_PER_S = 4.0  # one revolution per 90 s
COLOR_SHAPE_MIST_ALPHA = 22  # how much denser the haze is inside a swirl
# The school of bubbles, likewise melted in: a faint round lift with no rim and no
# highlight, drifting on the same slow Lissajous as before (per-bubble phase, so
# the school never marches in step). They are still pushed back out of both swirls
# and kept inside the page on every rebuild, so they stay in the clear band
# between them.
#
# A round of "clearer bubbles" (Difference-mode inversion in a ring plus a large
# highlight) was reverted, and the later rim+sheen version was melted away with the
# slabs for the same reason: anything with a closed bright ring concentric with the
# outline, or a highlight big enough to read as a pupil, stops being haze.
COLOR_BUBBLE_MIST_ALPHA = 15
COLOR_BUBBLE_SWAY_RAD_PER_MS = 0.00025  # ~25 s per sway
COLOR_BUBBLE_SWAY_SPEEDUP = 1.2  # extra sway speed at full music level
COLOR_BUBBLE_SWAY_X = 0.014  # sideways wander, fraction of the page width
COLOR_BUBBLE_SWAY_Y = 0.020  # vertical wander, fraction of the page height
COLOR_BUBBLE_CLEARANCE = 0.02  # least gap to a swirl's edge, x min(w,h)
# Film grain over the backdrop: a cached noise tile used as a texture brush.
# The tile is built in DEVICE pixels (scaled by the window's devicePixelRatio and
# tagged with it), so one grain dot is one physical pixel -- at 200% scaling a
# logical-pixel tile made every dot 2x2 physical pixels and the grain looked
# coarse. The offset is re-rolled a few times a second rather than every frame:
# at 60 Hz it read as the whole frosted layer vibrating.
COLOR_NOISE_ALPHA = 8
COLOR_NOISE_TILE = 96
COLOR_NOISE_DRIFT_PX = 2
COLOR_NOISE_STEP_MS = 110
# The whole 音乐色彩 composite (backdrop + shapes + strands + frost + grain) is
# cached and only rebuilt this often. Drawing it live costs ~14.5 ms per frame at
# 1920x1200 device pixels, which is most of a 60 fps budget on its own -- and the
# music menu, being a translucent child, makes the page repaint its whole
# background on every frame of its own animation, so the lag showed up there
# first. The shapes and strands drift slowly enough that 25 Hz is invisible.
COLOR_FRAME_STEP_MS = 40
# While the window is being dragged bigger or smaller the size changes every
# frame, and rebuilding the blur layers plus the composite there costs ~26 ms a
# frame. The existing composite is stretched instead, and only rebuilt once the
# size has held still this long -- which is what makes the drag feel stuck on
# this effect. 140 ms is below the time it takes to notice the blur is stale.
COLOR_RESIZE_SETTLE_MS = 140

# How hard the volume slider shoves the speaker icon beside it, outward along
# the bar. PUSH_PX is the steady force applied while the pointer holds the fill
# against an end -- the spring only overshoots the wall in proportion to its
# speed, so a slow drag barely penetrates and needs this to be visible at all.
# WALL_KICK adds a one-shot impulse from a real overshoot, which is what makes
# a jump straight to the end snap. MAX_OFFSET caps the shove.
VOLUME_ICON_PUSH_PX = 1.2
VOLUME_ICON_WALL_KICK = 45.0
VOLUME_ICON_MAX_OFFSET = 14.0

# Vinyl record interaction. While stowed the record peeks out of the sleeve's
# right edge by this fraction of its own diameter -- enough to aim at, and the
# only part that can be grabbed. Once out it sits centred on the cover.
# Dragging it right by STOW_DRAG_PX throws it back; dragging the peeked sliver
# left by PULL_DRAG_PX slides it out by hand (a plain click still pulls it out).
VINYL_PEEK_FRACTION = 0.16
VINYL_STOW_DRAG_PX = 46.0
VINYL_PULL_DRAG_PX = 6.0
# The record's centre label, as a fraction of its radius. Matches the paper
# circle drawn in _build_record_pixmap, and is the only area from which the
# throw-back drag may start -- pressing the outer black disc means scratching.
VINYL_LABEL_RADIUS_RATIO = 0.34


_UI_FONT_PROTOTYPES: dict = {}


def ui_font(size: int = 9, weight=None):
    """Return the interface font at *size* with the sans-serif fallback stack.

    The prototype is cached per (size, weight) and callers get a copy: this is
    called from paint paths (the title/artist/spec lines, the lyric rows) and
    building the family list over and over costs a Windows font-database lookup
    each time. Qt copies share their font engine, so a copy is free, while
    callers stay free to tweak what they get (the title line sets DemiBold on
    its own copy).
    """
    key = (int(size), weight)
    prototype = _UI_FONT_PROTOTYPES.get(key)
    if prototype is None:
        family = _ACTIVE_FONT_STACK[0] if _ACTIVE_FONT_STACK else UI_FONT_FAMILY
        prototype = QFont(family, size)
        try:
            prototype.setFamilies(list(_ACTIVE_FONT_STACK))
            # As above, for the cached prototype.
        except Exception:
            pass
        if weight is not None:
            prototype.setWeight(weight)
        _UI_FONT_PROTOTYPES[key] = prototype
    return QFont(prototype)


# Settings
SETTINGS_ORG = "AfterFrame"
SETTINGS_APP = "AfterFrame"
SETTINGS_KEY_FOLDER = "last_folder"
SETTINGS_KEY_FROSTED_CHROME = "frosted_chrome"
SETTINGS_KEY_FROSTED_LEVEL = "frosted_level"
SETTINGS_KEY_HOVER_LABELS = "hover_labels"
SETTINGS_KEY_LYRICS_ALIGN = "lyrics_align"
SETTINGS_KEY_MUSIC_DIR = "music_dir"
SETTINGS_KEY_PCM_ENGINE = "pcm_engine"
SETTINGS_KEY_VISUALIZER = "visualizer"
SETTINGS_KEY_WIPE = "wipe_transition"

# Where the lyric lines sit in their panel, left to right; the middle one is how
# the lyrics have always been drawn. The label is what the settings row's level
# bar shows, the index is what gets persisted.
LYRICS_ALIGNMENTS = ("靠左", "居中", "靠右")
DEFAULT_LYRICS_ALIGN = 1

# Startup reveal: the window grows while staying grey, then a coloured band
# sweeps left to right and the real UI appears in its wake.
WIPE_DURATION = 520

# Minimize / restore animations
MINIMIZE_SHUTDOWN_DURATION = 420
RESTORE_SCAN_DURATION = 420

# The compositor's blur material cannot be captured into the minimize / close
# snapshot (it lives behind the window), so the chrome is faded to flat BEFORE
# those animations start and faded back after a restore: by the time the pixmap
# is taken it is a truthful picture of the window. Length of each of those two
# fades -- see `_begin_chrome_flatten` in window.py.
CHROME_FLAT_DURATION = 160

# ...but only where the blur is actually on screen. Measured against a checkered
# backdrop: the music page's thin wash (alpha 26) leaves the material at a luma
# sigma of 51.4, while the dashboard and settings pages (alpha 180 at the 标准
# level) leave 19.1, which is barely visible. Fading there would add the pre-roll
# delay for nothing, so a strip whose wash is at least this opaque skips it.
# The frosted level moves those alphas, so this rule follows the level as well:
# 微透 (235) skips the pre-roll, 通透 (120) goes back to taking it.
CHROME_WASH_HIDES_FROST_ALPHA = 200

# Audio
# `.ncm` is not an audio container: it is Netease Cloud Music's wrapper around a
# plain mp3/flac stream and is unpacked before playback (see `afterframe.ncm`).
SUPPORTED_AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".wma", ".ncm"}
# Shown in the info panel's spec line as the container the *file on disk* uses,
# so a decoded flac is still reported as coming from an ncm.
MUSIC_SOURCE_NCM = "NCM"

# Vinyl / scratch settings
# The pair below is self-consistent: one full turn (360 deg) at the normal
# spin rate equals exactly 3 s of audio, so in PCM-engine mode the record
# angle and the playhead stay locked like a real turntable.
VINYL_MS_PER_DEG = 8.3333  # audio ms per degree of record rotation
VINYL_SPIN_DEG_PER_MS = 0.12  # normal play spin (~3 s per revolution)
VINYL_SCRATCH_SENSITIVITY = 1.0  # speed -> playback-rate sensitivity
VINYL_MAX_SCRATCH_DELTA_DEG = 1440.0  # cap total scratch rotation (4 turns)
VINYL_INERTIA_TAU_MS = 200.0  # paused visual coast-down time constant
VINYL_VEL_EMA = 0.5  # smoothing factor for per-event scratch velocity
VINYL_LIFT_EASE_MS = 70.0  # lift ease time while starting/stopping a scratch
VINYL_RELEASE_TAU_MS = 320.0  # PCM engine: ease release speed back to 1x
VINYL_RELEASE_SPEED_CLAMP = 3.5  # PCM engine: |release speed| cap in 1x units
VINYL_RATE_RETURN_TAU_MS = 120.0  # (Qt fallback) time constant to reach 1x
VINYL_RATE_MIN = 0.35
VINYL_RATE_MAX = 2.2
VINYL_RELEASE_RATE_MIN = 0.5
VINYL_RELEASE_RATE_MAX = 2.0
VINYL_BACKWARD_DRIFT_MS = 80  # tighter sync when scratching backward
VINYL_FORWARD_DRIFT_BASE_MS = 120
VINYL_FORWARD_LAG_MS = 400
VINYL_DRAG_LIFT_SCALE = 1.04  # record lift while scratching
VINYL_LABEL_TINT_BLEND = 0.25  # cover color blend into label
VINYL_HOVER_LIGHT_RADIUS_RATIO = 0.75  # light radius vs record radius
VINYL_HOVER_LIGHT_ALPHA = 95  # max light intensity at cursor center
VINYL_LABEL_RING_TEXT_SIZE_RATIO = 0.042  # tiny text size vs record size
VINYL_SHEEN_ALPHA = 24  # base alpha of the rotating groove sheen

# Tonearm (fractions of the sleeve size unless noted)
