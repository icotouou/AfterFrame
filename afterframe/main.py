import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from afterframe import ncm
from afterframe.constants import TOOLTIP_STYLE, active_font_stack, use_preferred_font
from afterframe.media_log import quiet_ffmpeg_log
from afterframe.window import AfterFrameWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AfterFrame")
    app.setApplicationDisplayName("AfterFrame")

    # Qt's FFmpeg backend prints a full stream listing to stderr for every
    # loaded track; that is libavformat talking, not Qt's logger, so it needs
    # FFmpeg's own log level rather than a Qt logging rule.
    #
    # qt.text.font.db's OpenType lines are left alone on purpose -- see
    # media_log's module docstring.
    quiet_ffmpeg_log()

    # Interface-wide sans-serif; stylesheets that only set a size
    # inherit this family.
    #
    # Resolved after the QApplication exists, because choosing between the default
    # family and a variable-weight one needs the font database. `use_preferred_font`
    # also drops ui_font's prototype cache, which is otherwise holding prototypes
    # built for the previous family.
    family = use_preferred_font()
    base_font = QFont()
    try:
        base_font.setFamilies(list(active_font_stack()))
        # As above: the application font falls back to one family.
    except Exception:
        pass
    app.setFont(base_font)
    app.setProperty("afterframe_font_family", family)

    # One tooltip look for the whole app.
    #
    # Qt falls back to the palette's black text when it cannot resolve a QToolTip
    # rule, which is invisible against the dark tip background used here. The rule
    # was previously only copy-pasted onto the music page's popup panels, so the
    # settings page's tooltips stayed black-on-dark. Measured: with no rule
    # anywhere the tip label's windowText is (0, 0, 0); the same rule set on the
    # APPLICATION takes effect (as does setting it on the widget or its parent),
    # so it is defined once here instead of per widget -- and being application
    # level it survives each widget's own setStyleSheet call.
    app.setStyleSheet(TOOLTIP_STYLE)

    # Unpacked ncm tracks are large plain-audio copies; they are only useful
    # while the app runs, so they never outlive it.
    app.aboutToQuit.connect(ncm.clear_cache)

    window = AfterFrameWindow()
    window.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
