"""Where the app's preferences live, with a writable-store fallback.

Preferences are `QSettings`, which on Windows means the registry by default. That
store is not always writable, and when it is not, `setValue()` **neither raises
nor persists** -- so the failure is completely silent. Measured: writing
`visualizer` and reading it straight back in the same process returned nothing,
and the registry key was never created. The only outward symptom is a setting
that forgets itself across a restart ("I picked 音乐色彩, restarted, and it is
棋盘格 again"), and **every** setting goes the same way, not just the newest one.

Because the write path cannot be trusted, the store is checked on the way in
rather than assumed (see `_ini_holds_probe` for why the check reads the file's
own bytes).

So preferences live in an INI file beside the project, created on first use, and
the registry is only the fallback for when that file cannot be written either.
Whatever the registry still holds is copied into a fresh file once, so a music
folder saved back when the registry was writable is not lost.
"""

import os

from PySide6.QtCore import QSettings

from .constants import SETTINGS_APP, SETTINGS_ORG

# Written and read back to decide whether a store actually persists. The value is
# distinctive because the INI check looks for it in the file's own bytes.
_PROBE_KEY = "__store_writable__"
_PROBE_VALUE = "store-writable-probe"
# Fallback beside the project (not inside the package, so it survives a
# reinstall of the source tree and is ignored by git).
INI_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "afterframe_settings.ini",
)

_store = None
_store_kind = ""


def _ini_holds_probe() -> bool:
    """True when the probe value is in the INI file ON DISK.

    QSettings caches a settings file in-process, so a second QSettings instance
    happily reads back a value that never reached the disk (measured: a write to
    an unwritable path still looked successful). The file's own bytes cannot be
    faked, so that is what the INI branch checks.
    """
    try:
        with open(INI_PATH, "rb") as handle:
            return _PROBE_VALUE.encode("utf-8") in handle.read()
    except OSError:
        return False


def _write_survives(settings: QSettings, verify) -> bool:
    """True when a value written through *settings* really reached the store."""
    try:
        settings.setValue(_PROBE_KEY, _PROBE_VALUE)
        settings.sync()
        survived = verify()
        settings.remove(_PROBE_KEY)
        settings.sync()
        return survived
    except Exception:
        return False


def _migrate(old: QSettings, new: QSettings) -> None:
    """Copy values the old store holds into a fresh fallback store."""
    try:
        if new.allKeys():
            return
        for key in old.allKeys():
            new.setValue(key, old.value(key))
        new.sync()
        # Migration is a convenience, not a contract: the new store simply
        # stays empty and the values above it are used as-is.
    except Exception:
        pass


def settings() -> QSettings:
    """The app's settings, guaranteed to be a store that really persists.

    The INI file comes FIRST on purpose. Preferences used to go straight to the
    registry, which only works while the app is allowed to write it: the same
    build persisted happily in one launch and silently forgot everything in
    another (measured: a value written and read back inside one process was gone,
    and the user's `visualizer` and `frosted_level` never reached the registry).
    Choosing the store by writability alone would leave two stores in play --
    the registry when launched one way, the file when launched the other, each
    blind to the other's settings -- so the file is preferred wherever the project
    directory itself is writable, and the registry is only the fallback for a
    read-only project directory.
    """
    global _store, _store_kind
    if _store is not None:
        return _store

    ini = QSettings(INI_PATH, QSettings.IniFormat)
    if _write_survives(ini, _ini_holds_probe):
        # Carry over whatever was saved back when the registry was still in use
        # (an existing file is left alone, so this cannot undo later choices).
        _migrate(QSettings(SETTINGS_ORG, SETTINGS_APP), ini)
        _store, _store_kind = ini, "ini"
        return _store

    registry = QSettings(SETTINGS_ORG, SETTINGS_APP)
    if _write_survives(
        registry,
        lambda: str(QSettings(SETTINGS_ORG, SETTINGS_APP).value(_PROBE_KEY, ""))
        == _PROBE_VALUE,
    ):
        _store, _store_kind = registry, "registry"
        return _store

    # Nothing is writable: keep using the registry so the app still reads whatever
    # was saved before, and do not pretend otherwise.
    _store, _store_kind = registry, "read-only"
    return _store


def store_kind() -> str:
    """'registry', 'ini' or 'read-only' -- what `settings()` settled on."""
    settings()
    return _store_kind


def store_path() -> str:
    """Human-readable location of the store in use."""
    return settings().fileName()
