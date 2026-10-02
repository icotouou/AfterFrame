"""Quiet the media backend's stream listing.

Qt's FFmpeg media backend calls `av_dump_format()` whenever it opens a file,
and that prints the whole stream listing to stderr at *info* level -- for every
track that is loaded:

    Input #0, flac, from 'C:/.../some.flac':
      Metadata:
        ALBUM           : ...
      Duration: 00:02:37.24, start: 0.000000, bitrate: 4836 kb/s
      Stream #0:0: Audio: flac, 192000 Hz, stereo, s32 (24 bit)

The dump comes from libavformat itself at the C level, so Qt's own logging
categories cannot filter it (`QLoggingCategory.setFilterRules(
"qt.multimedia.ffmpeg.info=false")` was measured to change nothing). Lowering
FFmpeg's own log level is what works.

The Qt wheel ships its FFmpeg libraries, and Qt has already loaded avutil by
the time a track is opened. Loading the same DLL path returns that same module,
so `av_log_set_level` applies to the backend's logging as well -- verified by
loading a track before and after: the stream listing disappears while playback
metadata is still reported correctly.

Only the level is raised (info -> error), never silenced outright: a genuine
decode or demux failure is still printed.

`qt.text.font.db`'s "OpenType support missing" lines are deliberately NOT
filtered. They can be (the category emits them at info level, so
`qt.text.font.db.info=false` removes them), but they were kept on purpose: the
UI font stack is a tuned choice, a track title really does contain glyphs it
cannot shape, and a diagnostic that is telling the truth should not be hidden.
"""

from __future__ import annotations

import ctypes
import os

_FFMPEG_QUIETED = False

_AV_LOG_ERROR = 16


def quiet_ffmpeg_log() -> bool:
    """Raise FFmpeg's log level so media probes stop printing. Idempotent.

    Returns whether the level was set. Never raises: this is log hygiene, so a
    packaging difference must not stop the app from starting.
    """
    global _FFMPEG_QUIETED
    if _FFMPEG_QUIETED:
        return True
    try:
        import PySide6

        package = os.path.dirname(os.path.abspath(PySide6.__file__))
    except Exception:
        return False

    # The library name carries FFmpeg's major version, so find it instead of
    # pinning a version that a PySide6 upgrade would invalidate.
    candidates = []
    try:
        for name in os.listdir(package):
            lowered = name.lower()
            if lowered.startswith("avutil") and lowered.endswith(".dll"):
                candidates.append(os.path.join(package, name))
    except OSError:
        return False
    if not candidates:
        return False

    # Highest version first, so a future side-by-side install picks the newer.
    candidates.sort(reverse=True)
    for path in candidates:
        try:
            avutil = ctypes.CDLL(path)
            avutil.av_log_set_level(ctypes.c_int(_AV_LOG_ERROR))
        except Exception:
            continue
        _FFMPEG_QUIETED = True
        return True
    return False
