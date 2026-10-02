"""Turntable-style audio engine for the vinyl scratch effect.

The current track is decoded to raw PCM by ffmpeg (streamed in a background
thread) and pushed through a QAudioSink. The playhead is a float frame index
that may move forward or backward at any speed, so dragging the record
backwards produces real reverse audio whose pitch follows the hand - like a
real turntable - instead of the choppy slow-forward-plus-seek emulation that
QMediaPlayer needs.

A push-mode sink drains at ITS OWN clock rate (44100 frames a second) whatever
we do with it, so the stream we hand it has to be sample-rate true: every pump
tick writes the frames that elapsed during that tick, and what the platter is
doing decides which frames those are. Writing fewer frames per tick does NOT
play the audio slower -- the sink simply runs dry and fills the gap with
silence, which is heard as a rumble at the tick rate. That mistake is what made
a released scratch (the ease spends ~1 s near 0x) sound like a broken speaker;
see `_render_owed` and `_sample_span`. Playback at exactly 1x still takes a
plain byte-slice copy, so the common case costs nothing extra.

That clock also has to be measured exactly: `QElapsedTimer.restart()` returns
whole milliseconds and drops the fraction, so a 16 ms tick reported 15 ms and
the engine credited the device ~0.5 ms less than the device consumed, every
tick. The queue drained to zero and stayed there, and the sink replaced the
shortfall with silence -- measured at 362 ms lost to truncation against 366 ms
of inserted silence in a 12 s run, which is the crackle that sounded like a bad
Bluetooth link. `_pump` now reads a cumulative nanosecond clock instead.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import threading
from array import array

from PySide6.QtCore import QElapsedTimer, QObject, QTimer, Signal

try:
    from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

    _MULTIMEDIA_OK = True
except Exception:  # pragma: no cover - QtMultimedia missing
    _MULTIMEDIA_OK = False

_SAMPLE_RATE = 44100
_FRAME_BYTES = 4  # stereo int16
_MAX_OUT_FRAMES = _SAMPLE_RATE // 10  # cap audio generated per pump (~100 ms)
_PREFILL_FRAMES = int(_SAMPLE_RATE * 0.05)  # cushion so scheduling jitter can't starve
_MIN_AUDIBLE_SPEED = 0.03  # a platter this close to still makes no sound
_SINK_BUFFER_FRAMES = int(_SAMPLE_RATE * 0.12)  # low latency for scratching
# How far the pitch may follow the platter. A hand on vinyl stays inside roughly
# 0.5-2x, but the page maps the MOUSE angle straight to rotation, so a drag can
# turn the record tens of times faster than a hand -- pitching that up reads as a
# chipmunk ("alien"), not as a scratch. So the cap is asymmetric: the pitch may
# fall below 1x (a braking platter really does drop in pitch) but never rise
# above it. Faster than 1x the audio SKIPS instead -- the platter runs ahead of
# the needle -- which keeps the sound recognisably a scratch instead of a
# sped-up squeak, and keeps the needle from falling behind the platter.
_PITCH_MAX = 1.0
_SPEED_CLAMP = 4.0  # platter speed accepted from the page (release inertia)
_PENDING_LIMIT = _SAMPLE_RATE * _FRAME_BYTES // 3  # never queue more than ~0.3 s
_DECODE_CHUNK = 1 << 16


_FFMPEG_PROBED: bool | None = None


def ffmpeg_available() -> bool:
    """Whether the PCM engine can run; the PATH probe is cached."""
    global _FFMPEG_PROBED
    if _FFMPEG_PROBED is None:
        _FFMPEG_PROBED = _MULTIMEDIA_OK and shutil.which("ffmpeg") is not None
    return _FFMPEG_PROBED


class VinylAudioEngine(QObject):
    """Plays one track as raw PCM and exposes a scratchable playhead."""

    ready = Signal(int)  # exact duration in ms, once decoding completes
    failed = Signal()  # decoding or audio output could not start
    finished = Signal()  # playhead reached the end during normal playback

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)

        self._format = None
        if _MULTIMEDIA_OK:
            self._format = QAudioFormat()
            self._format.setSampleRate(_SAMPLE_RATE)
            self._format.setChannelCount(2)
            self._format.setSampleFormat(QAudioFormat.Int16)

        # Decoded PCM (interleaved s16le stereo), fed by the decode thread.
        self._pcm = bytearray()
        self._lock = threading.Lock()
        self._frontier = 0  # frames decoded so far
        self._total = -1  # total frames (-1 until decoding completes)
        self._decode_done = False
        self._decode_failed = False
        self._gen = 0  # generation counter; invalidates stale decode threads
        self._proc: subprocess.Popen | None = None

        # Playback state. The playhead is a float frame index and may travel
        # past the track ends while scratching (silence there, like a record
        # spun past its grooves).
        self._playhead = 0.0
        # Source frame the resampler has produced up to. Kept as a float so the
        # sub-frame phase survives the tick boundary -- resetting it every tick
        # would step the waveform and buzz at the tick rate.
        self._gen_pos = 0.0
        # Output frames owed to the device for the elapsed real time, and audio
        # generated but not yet accepted by the sink.
        self._out_debt = 0.0
        self._pending = bytearray()
        self._speed = 1.0
        self._easing = False
        self._release_tau = 0.32  # seconds
        self._scratching = False
        self._playing = False
        self._pending_play = False
        self._finished_emitted = False

        self._volume = 1.0
        self._sink = None
        self._io = None

        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(16)
        self._pump_timer.timeout.connect(self._pump)
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(16)
        self._watch_timer.timeout.connect(self._watch_pending)
        self._clock = QElapsedTimer()
        # Nanosecond stamp of the previous pump, read from a clock that is never
        # restarted (see `_pump`: the millisecond API loses the fraction).
        self._last_ns = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def supported() -> bool:
        return ffmpeg_available()

    def open(self, path: str) -> bool:
        """Start decoding *path* in the background. False when unsupported."""
        self.stop()
        self._abort_decode()
        with self._lock:
            self._pcm = bytearray()
            self._frontier = 0
            self._total = -1
            self._decode_done = False
            self._decode_failed = False
        self._playhead = 0.0
        self._speed = 1.0
        self._easing = False
        self._scratching = False
        self._finished_emitted = False
        self._reset_output()

        if not ffmpeg_available():
            self._decode_failed = True
            self.failed.emit()
            return False

        self._gen += 1
        thread = threading.Thread(
            target=self._decode_run, args=(path, self._gen), daemon=True
        )
        thread.start()
        return True

    def play(self) -> None:
        """Start (or resume) playback; waits for the first decoded chunk."""
        if self._decode_failed:
            return
        self._finished_emitted = False
        if self._playing:
            return
        self._playing = True
        self._pending_play = True
        self._watch_timer.start()

    def pause(self) -> None:
        self._pending_play = False
        self._playing = False
        self._pump_timer.stop()
        self._watch_timer.stop()
        if self._sink is not None:
            self._sink.stop()
        self._io = None

    def stop(self) -> None:
        self.pause()
        self._playhead = 0.0
        self._speed = 1.0
        self._easing = False
        self._scratching = False
        self._finished_emitted = False
        self._reset_output()

    def seek(self, ms: float) -> None:
        """Jump the playhead silently (progress bar, lyric click)."""
        self._playhead = max(0.0, float(ms)) / 1000.0 * _SAMPLE_RATE
        self._finished_emitted = False
        # Anything already generated belongs to where we just left, so it is
        # dropped rather than played over the new position.
        self._reset_output()

    def _reset_output(self) -> None:
        """Re-anchor the resampler on the playhead (start, stop, seek)."""
        # Whole frames, so ordinary playback keeps taking the byte-slice copy
        # instead of the per-frame resampler (a fractional anchor would never
        # line up again).
        self._playhead = float(round(self._playhead))
        self._gen_pos = self._playhead
        self._out_debt = float(_PREFILL_FRAMES)
        self._pending = bytearray()

    def set_scratching(self, active: bool) -> None:
        self._scratching = bool(active)
        if active:
            self._finished_emitted = False

    def set_playhead_ms(self, ms: float) -> None:
        """Drive the playhead directly while scratching (may pass the ends)."""
        self._playhead = float(ms) / 1000.0 * _SAMPLE_RATE

    def release(self, speed0: float, tau: float = 0.32) -> None:
        """End a scratch: spin at *speed0* (1x units, may be negative) and
        ease back to normal speed, braking through zero like a platter."""
        self._scratching = False
        self._finished_emitted = False
        self._speed = max(-_SPEED_CLAMP, min(_SPEED_CLAMP, float(speed0)))
        self._easing = True
        self._release_tau = max(0.05, float(tau))

    def speed(self) -> float:
        return self._speed

    def position_ms(self) -> int:
        return max(0, int(self._playhead / _SAMPLE_RATE * 1000.0))

    def read_playhead_pcm(self, frames: int) -> bytes:
        """Return raw stereo PCM for *frames* ending at the playhead.

        Used by the music page to analyse loudness/bass for reactive visuals;
        returns whatever is decoded (may be short or empty near the start).
        """
        end = int(self._playhead)
        with self._lock:
            end = min(end, self._frontier)
            start = max(0, end - int(frames))
            if end <= start:
                return b""
            return bytes(self._pcm[start * _FRAME_BYTES : end * _FRAME_BYTES])

    def duration_ms(self) -> int:
        with self._lock:
            total = self._total
        if total < 0:
            return 0
        return int(total / _SAMPLE_RATE * 1000.0)

    def is_playing(self) -> bool:
        return self._playing

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))
        if self._sink is not None:
            self._sink.setVolume(self._volume)

    def shutdown(self) -> None:
        self._abort_decode()
        self.pause()

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------
    def _abort_decode(self) -> None:
        self._gen += 1
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.kill()
                # The ffmpeg child is being torn down anyway; if it has already
                # exited there is nothing left to kill.
            except Exception:
                pass

    def _decode_run(self, path: str, gen: int) -> None:
        cmd = [
            "ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn",
            "-acodec", "pcm_s16le", "-ar", str(_SAMPLE_RATE), "-ac", "2",
            "-f", "s16le", "pipe:1",
        ]
        kwargs = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **kwargs
            )
        except Exception:
            self._fail_decode(gen)
            return
        self._proc = proc

        try:
            while True:
                if gen != self._gen:
                    proc.kill()
                    return
                chunk = proc.stdout.read(_DECODE_CHUNK)
                if not chunk:
                    break
                with self._lock:
                    if gen != self._gen:
                        proc.kill()
                        return
                    self._pcm.extend(chunk)
                    self._frontier += len(chunk) // _FRAME_BYTES
        finally:
            try:
                proc.stdout.close()
                # Closing an already-closed pipe is fine, and the wait()
                # below is what actually reaps the child.
            except Exception:
                pass
            code = proc.wait()
            if gen != self._gen:
                return
            with self._lock:
                self._decode_done = True
                # Keep partial data from a nonzero exit; only fail when we
                # got nothing usable at all.
                self._decode_failed = self._frontier == 0
                if not self._decode_failed:
                    self._total = self._frontier
            if self._decode_failed:
                self.failed.emit()
            else:
                self.ready.emit(self.duration_ms())

    def _fail_decode(self, gen: int) -> None:
        if gen != self._gen:
            return
        with self._lock:
            self._decode_failed = True
        self.failed.emit()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def _watch_pending(self) -> None:
        """Main-thread poll that starts the sink once PCM is available."""
        if not self._pending_play:
            self._watch_timer.stop()
            return
        with self._lock:
            has_data = self._frontier > 0
            failed = self._decode_failed
        if failed:
            self._pending_play = False
            self._playing = False
            self._watch_timer.stop()
            self.failed.emit()
            return
        if has_data:
            self._pending_play = False
            self._watch_timer.stop()
            if self._start_output():
                self._pump_timer.start()

    def _start_output(self) -> bool:
        if self._sink is None:
            device = QMediaDevices.defaultAudioOutput()
            if device.isNull():
                return self._fail_output()
            self._sink = QAudioSink(device, self._format, self)
            self._sink.setBufferSize(_SINK_BUFFER_FRAMES * _FRAME_BYTES)
        self._sink.setVolume(self._volume)
        self._gen_pos = float(self._playhead)
        self._out_debt = float(_PREFILL_FRAMES)
        self._pending = bytearray()
        try:
            self._io = self._sink.start()
        except Exception:
            self._io = None
        if self._io is None:
            return self._fail_output()
        if self._sink.state() == QAudio.State.StoppedState:
            return self._fail_output()
        self._clock.start()
        self._last_ns = self._clock.nsecsElapsed()
        return True

    def _fail_output(self) -> bool:
        self._playing = False
        self._pending_play = False
        self.failed.emit()
        return False

    # ------------------------------------------------------------------
    # Pump
    # ------------------------------------------------------------------
    def _pump(self) -> None:
        if not self._playing:
            self._pump_timer.stop()
            return
        if self._io is None:
            return

        # Exact elapsed time. `QElapsedTimer.restart()` reports whole
        # milliseconds and does NOT carry the fraction, so a 16 ms tick handed
        # back 15 ms and half a millisecond was thrown away ~60 times a second.
        # The engine then credited the device 3-4% less audio than the device's
        # own clock had consumed, the queue drained to zero and stayed there,
        # and the sink filled the shortfall with silence: measured 362 ms lost
        # to truncation against 366 ms of inserted silence in a 12 s run, heard
        # as crackle. Cumulative nanoseconds end that.
        now_ns = self._clock.nsecsElapsed()
        dt_ms = max(0.0, (now_ns - self._last_ns) / 1e6)
        self._last_ns = now_ns

        # Release inertia: ease the speed back to 1x. A negative release
        # speed brakes through zero and spins back up, like a real platter.
        if self._easing and not self._scratching:
            factor = 1.0 - math.exp(-dt_ms / (self._release_tau * 1000.0))
            self._speed += (1.0 - self._speed) * factor
            if abs(self._speed - 1.0) < 0.004:
                self._speed = 1.0
                self._easing = False
                # Back on 1x: nudging the resampler onto a whole frame is
                # inaudible and lets the byte-slice copy take over again.
                self._gen_pos = round(self._gen_pos)

        # The device has been draining at its own rate for dt_ms, so that is
        # exactly how many frames it is owed -- NOT "as many as the record
        # moved", which is what starved it whenever the platter was slow.
        self._out_debt += dt_ms / 1000.0 * _SAMPLE_RATE
        # Never owe more than the sink can hold plus one tick's work. Past that
        # the "missing" audio could only be handed over as a catch-up burst
        # (which `_PENDING_LIMIT` would then cut up), so a machine that slept for
        # an hour would wake up and fast-forward through the track. Dropping the
        # excess leaves the audio a little late instead -- the quieter failure.
        debt_cap = float(_SINK_BUFFER_FRAMES + _MAX_OUT_FRAMES)
        if self._out_debt > debt_cap:
            self._out_debt = debt_cap
        owed = int(self._out_debt)
        if owed > 0:
            # Generate at most ~100 ms per tick and keep the rest owed: a tick
            # that ran long must not be written off, or the audio falls further
            # behind on every hitch for the rest of the track.
            render = min(owed, _MAX_OUT_FRAMES)
            self._out_debt -= render
            self._render_owed(render)
        self._flush_pending()

        with self._lock:
            done = self._decode_done
            total = self._total
        if (
            not self._scratching
            and not self._finished_emitted
            and done
            and total >= 0
            and self._speed > 0
            and self._playhead >= total
        ):
            self._playhead = float(total)
            self._gen_pos = float(total)
            self._finished_emitted = True
            self.finished.emit()

    def _render_owed(self, owed: int) -> None:
        """Generate exactly *owed* output frames at the current platter speed.

        Pitch comes from the resampler: the span the platter covered this tick is
        stretched (slow platter) or squeezed (fast one) into the frames the device
        asked for.
        """
        if self._scratching:
            # The hand owns the playhead; the span it travelled is the audio.
            target = self._playhead
        else:
            target = self._gen_pos + self._speed * owed

        step = (target - self._gen_pos) / owed
        if abs(step) > _PITCH_MAX:
            # Faster than the pitch cap. Play the frames right next to where the
            # hand is, at 1x, and skip the rest rather than pitching up: this is
            # the sound the old frame-dropping build made, without the drops (and
            # without the hiss of a sink running dry).
            if step > 0:
                self._pending += self._sample_span(target - owed, _PITCH_MAX, owed)
            else:
                self._pending += self._sample_span(target, -_PITCH_MAX, owed)
            # Stay glued to the hand: letting the audio lag behind it is what
            # turned a fast scratch into noise.
            self._gen_pos = target
        else:
            self._pending += self._sample_span(self._gen_pos, step, owed)
            self._gen_pos += step * owed
        if not self._scratching:
            # What is heard and what the UI shows stay the same number.
            self._playhead = self._gen_pos

    def _flush_pending(self) -> None:
        """Hand the sink as much as it will take, keep the rest for next tick."""
        if not self._pending:
            return
        written = self._io.write(bytes(self._pending))
        if written:
            del self._pending[:written]
        if len(self._pending) > _PENDING_LIMIT:
            del self._pending[: len(self._pending) - _PENDING_LIMIT]

    def _sample_span(self, start: float, step: float, count: int) -> bytes:
        """*count* output frames read from the source at *step* frames per frame.

        Linear interpolation, which is what makes a braked platter really drop in
        pitch, a reversed one really run backwards and a stopped one really fall
        silent -- none of which a push-mode sink can be talked into by writing
        fewer frames. Exactly 1x takes a byte-slice copy, so ordinary playback
        never enters the per-frame loop.
        """
        total_bytes = count * _FRAME_BYTES
        if abs(step) < _MIN_AUDIBLE_SPEED:
            # A record that is not moving makes no sound. This also keeps a
            # stopped platter from emitting a DC level, which would thump.
            return bytes(total_bytes)

        with self._lock:
            frontier = self._frontier
            pcm = self._pcm

        if step == 1.0 and start == int(start):
            s = max(0, int(start))
            e = min(s + count, frontier)
            data = bytes(pcm[s * _FRAME_BYTES : e * _FRAME_BYTES])
            return data + bytes(total_bytes - len(data))

        # Window of source frames the span touches, copied once so the loop reads
        # from an array instead of a locked bytearray.
        end = start + step * count
        lo = max(0, int(math.floor(min(start, end))) - 1)
        hi = min(frontier, int(math.ceil(max(start, end))) + 2)
        window = array("h")
        if hi > lo:
            window.frombytes(bytes(pcm[lo * _FRAME_BYTES : hi * _FRAME_BYTES]))

        out = array("h", bytes(total_bytes))
        last = len(window) - 4
        pos = start - lo
        index = 0
        for _ in range(count):
            frame = int(pos)
            j = frame + frame
            if 0 <= j <= last:
                frac = pos - frame
                left = window[j]
                right = window[j + 1]
                out[index] = int(left + (window[j + 2] - left) * frac)
                out[index + 1] = int(right + (window[j + 3] - right) * frac)
            # Positions outside the decoded range stay silent, like a needle
            # that has run off the record.
            pos += step
            index += 2
        return out.tobytes()
