"""Netease Cloud Music `.ncm` container support.

`ncm` is a thin wrapper around a normal mp3/flac stream: the container carries
an AES-encrypted audio key, a masked+base64+AES metadata blob and a plain cover
image, and the audio itself is XORed with a keystream derived from that key. It
is not something ffmpeg can read, so the file is unpacked to a plain audio file
in a per-session cache directory and the rest of the app keeps working with
ordinary paths (see `decode`).

Everything here is standard library only. The app deliberately has no crypto
dependency, and only two AES-128-ECB blocks are ever needed (the 128-byte key
blob and the metadata blob), so a small table-driven AES lives in this file.
Its block function is checked against the FIPS-197 known-answer vectors at
import time -- a silently wrong AES would look exactly like "this file is not
really an ncm", which is the one failure mode worth paying for.

The keystream is a variant of RC4 with the swap step dropped, and `j` is taken
as `i + s_box[i]` modulo 256. Because `i` itself only ever wraps through 0-255,
the stream repeats every 256 bytes, which is what lets `_Keystream.apply` be a
table XOR instead of a byte-at-a-time key schedule. `_Keystream` verifies the
periodicity rather than assuming it, so an edit that breaks it fails loudly
instead of producing noise that still "plays".

The cover region and the audio start are one detail seen twice. Its measured
layout is: the cover-length field, a 4-byte repeat of that value, the image, and
then the audio immediately. Read the image as "field + cover_len" and it starts
4 bytes late; start the audio there instead and every decrypted byte is shifted,
so the stream reads as noise and looks exactly like "this uses a different
cipher". Verified against ncmdump 1.5.1 output.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field

from .constants import no_window_kwargs

NCM_MAGIC = b"CTENFDAM"

# The two AES-128-ECB keys the format uses.
_KEY_CORE = bytes.fromhex("687a4852416d736f356b496e62617857")
_KEY_META = bytes.fromhex("2331346c6a6b5f215c5d2630553c2728")

_KEY_PREFIX = b"neteasecloudmusic"
_META_PREFIX = b"163 key(Don't modify):"
_MUSIC_PREFIX = b"music:"

# Audio container signatures, checked at the start of the decrypted stream and
# after the 17-byte pad some builds leave in front of it.
_MAGIC_EXT = (
    (b"fLaC", ".flac"),
    (b"ID3", ".mp3"),
    (b"\xff\xfb", ".mp3"),
    (b"\xff\xf3", ".mp3"),
    (b"\xff\xf2", ".mp3"),
    (b"\xff\xfa", ".mp3"),
    (b"OggS", ".ogg"),
    (b"RIFF", ".wav"),
)
_PAD_SKIP = 17

_CACHE_DIR_NAME = "ncm"
_OK_SUFFIX = ".ok"

# Measured layout of the cover: the length field, a repeat of that same value,
# then the image (`cover_len` bytes, ending exactly on the PNG/JPEG end marker),
# and the audio immediately after. Reading the image as "field + cover_len"
# starts it 4 bytes late, and starting the audio there instead shifts every
# decrypted byte -- which reads as pure noise, indistinguishable from "this file
# uses a different cipher". Verified byte-for-byte against ncmdump 1.5.1 output.
_COVER_REPEAT = 4


# ----------------------------------------------------------------------
# AES-128-ECB (decrypt only)
# ----------------------------------------------------------------------
_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76"
    "ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d83115"
    "04c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f84"
    "53d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa8"
    "51a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d1973"
    "60814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479"
    "e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a"
    "703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df"
    "8ca1890dbfe6426841992d0fb054bb16"
)
_INV_SBOX = bytearray(256)
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _gmul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _expand_key(key: bytes) -> list:
    words = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        temp = list(words[i - 1])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[x] for x in temp]
            temp[0] ^= _RCON[i // 4 - 1]
        words.append([words[i - 4][j] ^ temp[j] for j in range(4)])
    return [byte for word in words for byte in word]


def _inv_mix_columns(state: list) -> list:
    out = list(state)
    for col in range(4):
        a = state[4 * col:4 * col + 4]
        for row in range(4):
            out[4 * col + row] = (
                _gmul(a[row], 0x0E)
                ^ _gmul(a[(row + 1) % 4], 0x0B)
                ^ _gmul(a[(row + 2) % 4], 0x0D)
                ^ _gmul(a[(row + 3) % 4], 0x09)
            )
    return out


def _decrypt_block(block: bytes, round_keys: list) -> bytes:
    """One AES-128 block, inverse cipher order (see FIPS-197 §5.3)."""
    state = [block[i] ^ round_keys[160 + i] for i in range(16)]
    for rnd in range(9, 0, -1):
        state = [_INV_SBOX[x] for x in state]
        shifted = list(state)
        for row in range(4):
            for col in range(4):
                shifted[row + 4 * ((col + row) % 4)] = state[row + 4 * col]
        state = shifted
        key = round_keys[16 * rnd:16 * rnd + 16]
        state = [state[i] ^ key[i] for i in range(16)]
        state = _inv_mix_columns(state)
    state = [_INV_SBOX[x] for x in state]
    shifted = list(state)
    for row in range(4):
        for col in range(4):
            shifted[row + 4 * ((col + row) % 4)] = state[row + 4 * col]
    return bytes([shifted[i] ^ round_keys[i] for i in range(16)])


def _aes_decrypt(data: bytes, key: bytes) -> bytes:
    """ECB-decrypt *data* (length must be a multiple of 16)."""
    round_keys = _expand_key(key)
    return b"".join(
        _decrypt_block(data[i:i + 16], round_keys) for i in range(0, len(data), 16)
    )


def _self_check() -> None:
    """FIPS-197 C.1 known-answer vector. A wrong AES would masquerade as a
    malformed ncm file, so fail at import instead."""
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    cipher = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    plain = bytes.fromhex("00112233445566778899aabbccddeeff")
    if _decrypt_block(cipher, _expand_key(key)) != plain:
        raise RuntimeError("afterframe.ncm: AES self-check failed")
    # Negative control: the same call with a corrupted key must disagree.
    bad = bytearray(key)
    bad[0] ^= 0xFF
    if _decrypt_block(cipher, _expand_key(bytes(bad))) == plain:
        raise RuntimeError("afterframe.ncm: AES self-check is not discriminating")


_self_check()


def _pkcs7_strip(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    return data[:-pad] if 0 < pad <= 16 else data


# ----------------------------------------------------------------------
# Audio keystream
# ----------------------------------------------------------------------
class _Keystream:
    """The 256-byte keystream ncm XORs its audio with."""

    __slots__ = ("stream",)

    def __init__(self, key: bytes) -> None:
        box = list(range(256))
        last = 0
        for i in range(256):
            last = (box[i] + last + key[i % len(key)]) & 0xFF
            box[i], box[last] = box[last], box[i]
        # j is (i + 1) & 0xff, so the stream repeats every 256 bytes. Verified
        # rather than assumed: the fast path below is only valid if it holds.
        stream = bytearray(512)
        for index in range(512):
            j = (index + 1) & 0xFF
            stream[index] = box[(box[j] + box[(box[j] + j) & 0xFF]) & 0xFF]
        if stream[:256] != stream[256:]:
            raise RuntimeError("afterframe.ncm: keystream is not 256-periodic")
        self.stream = bytes(stream[:256])

    def apply(self, data: bytes, offset: int = 0) -> bytes:
        """XOR *data* with the keystream, starting at stream position *offset*.

        `offset` is the absolute position in the audio stream, so a caller
        decrypting in chunks keeps the phase true across chunk boundaries.
        """
        if not data:
            return b""
        phase = offset & 0xFF
        # The stream repeats every 256 bytes, so each aligned 256-byte block is
        # one big-int XOR (a single C loop). Blocks stay separate because a
        # whole-buffer XOR would carry into an extra byte when the top bits
        # collide, and `to_bytes` would then raise.
        table = int.from_bytes(self.stream[phase:] + self.stream[:phase], "little")
        packed = memoryview(data)
        span = len(data) & ~0xFF
        out = bytearray(span)
        for start in range(0, span, 256):
            value = int.from_bytes(packed[start:start + 256], "little") ^ table
            out[start:start + 256] = value.to_bytes(256, "little")
        for index in range(span, len(data)):
            out.append(data[index] ^ self.stream[(phase + index) & 0xFF])
        return bytes(out)


# ----------------------------------------------------------------------
# Container
# ----------------------------------------------------------------------
@dataclass
class _Container:
    key: bytes
    meta: dict
    cover: bytes
    audio_offset: int
    format_hint: str


def _read_uint32(handle) -> int:
    raw = handle.read(4)
    if len(raw) != 4:
        raise ValueError("ncm: truncated header")
    return struct.unpack("<I", raw)[0]


def _parse(path: str) -> _Container:
    with open(path, "rb") as handle:
        if handle.read(8) != NCM_MAGIC:
            raise ValueError("ncm: bad magic")
        handle.seek(2, os.SEEK_CUR)  # fixed 0x0170 gap
        key_len = _read_uint32(handle)
        key_blob = _pkcs7_strip(
            _aes_decrypt(bytes(b ^ 0x64 for b in handle.read(key_len)), _KEY_CORE)
        )
        if not key_blob.startswith(_KEY_PREFIX):
            raise ValueError("ncm: audio key did not decrypt")
        key = key_blob[len(_KEY_PREFIX):]

        meta_len = _read_uint32(handle)
        raw_meta = bytes(b ^ 0x63 for b in handle.read(meta_len))
        meta: dict = {}
        if raw_meta.startswith(_META_PREFIX):
            try:
                decoded = _pkcs7_strip(
                    _aes_decrypt(base64.b64decode(raw_meta[len(_META_PREFIX):]), _KEY_META)
                )
                if decoded.startswith(_MUSIC_PREFIX):
                    meta = json.loads(decoded[len(_MUSIC_PREFIX):].decode("utf-8"))
            except Exception:
                meta = {}

        handle.seek(5, os.SEEK_CUR)  # cover CRC + unknown
        cover_len = _read_uint32(handle)
        # Measured layout: the length field, a repeat of that same value, then
        # the image itself (`cover_len` bytes, ending on the PNG/JPEG end
        # marker), and the audio immediately after. Reading the image as
        # "field + cover_len" would start it 4 bytes late; starting the audio
        # there instead would shift every decrypted byte and read as noise.
        # See _COVER_REPEAT.
        remaining = os.fstat(handle.fileno()).st_size - handle.tell()
        image = b""
        if 0 < cover_len <= remaining:
            handle.seek(_COVER_REPEAT, os.SEEK_CUR)  # repeated length field
            image = handle.read(cover_len)
        return _Container(key, meta, image, handle.tell(), str(meta.get("format", "")))


def _sniff_format(head: bytes, hint: str) -> tuple:
    """Return (extension, prefix_bytes_to_skip) for the decrypted stream."""
    for magic, ext in _MAGIC_EXT:
        if head.startswith(magic):
            return ext, 0
    for magic, ext in _MAGIC_EXT:
        if head[_PAD_SKIP:].startswith(magic):
            return ext, _PAD_SKIP
    # Unknown header: trust the metadata's format name rather than guessing.
    if hint in ("flac", "mp3", "ogg", "wav"):
        return "." + hint, 0
    return "", 0


@dataclass
class DecodedTrack:
    """A decoded ncm file plus the tags/cover the container carried."""

    path: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    bitrate: int = 0
    audio_format: str = ""
    cover_data: bytes = field(default=b"", repr=False)
    error: str = ""


def _cache_dir() -> str:
    """Directory holding unpacked audio.

    The path is forced absolute: `tempfile.gettempdir()` returns a *relative*
    path when every candidate directory is rejected, and a relative cache then
    lands inside the source tree -- a decoded album's worth of audio written next
    to the package. Never join a cache path onto a possibly-relative base.
    """
    base = tempfile.gettempdir()
    if not base or not os.path.isabs(base):
        base = tempfile.mkdtemp(prefix="afterframe-")
    root = os.path.join(base, _CACHE_DIR_NAME)
    os.makedirs(root, exist_ok=True)
    return root


def _cache_path(path: str, ext: str) -> str:
    digest = hashlib.sha1(os.path.abspath(path).encode("utf-8", "replace")).hexdigest()
    return os.path.join(_cache_dir(), digest + ext)


def _cached_ok(audio_path: str) -> bool:
    """A cached decode only counts when its success marker is present.

    Without the marker a cached file could be the leftovers of a failed decode
    (an earlier build wrote the audio layer without validating it), and the
    caller would happily play noise.
    """
    return os.path.isfile(audio_path) and os.path.isfile(audio_path + _OK_SUFFIX)


def _mark_ok(audio_path: str) -> None:
    try:
        with open(audio_path + _OK_SUFFIX, "wb"):
            pass
        # Best effort: the marker only records that this file was decoded
        # before, so failing to write it costs a re-decode, nothing more.
    except OSError:
        pass


def clear_cache() -> None:
    """Drop decoded audio. Called on shutdown; files are plain music."""
    try:
        shutil.rmtree(_cache_dir(), ignore_errors=True)
        # Teardown runs at exit; a cache that cannot be removed now is
        # left for the next start to sweep.
    except Exception:
        pass


def _looks_like_audio(path: str) -> bool:
    """True when ffprobe can see real audio in the decoded file.

    The container is easy to unpack but the audio layer is not: a file from a
    client build that uses a different cipher decrypts to plausible-looking
    random bytes. Playing that would be worse than refusing, so the decoded
    stream has to survive a probe before it counts as success.

    `returncode` alone is NOT enough: on random data ffprobe still exits 0
    while reporting "Format flac detected only with low score of 1" and a
    stream with no codec parameters (`flac,0`). Real audio always yields a
    codec name plus a positive sample rate.
    """
    if not shutil.which("ffprobe"):
        return True  # cannot check; do not block playback on a missing tool
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,sample_rate", "-of", "default=nw=1:nk=1",
             path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False, **no_window_kwargs(),
        )
    except Exception:
        return True
    if result.returncode != 0:
        return False
    fields = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(fields) < 2:
        return False
    codec, rate = fields[0], fields[1]
    if codec in ("", "unknown", "none"):
        return False
    try:
        return int(rate) > 0
    except ValueError:
        return False


def decode(path: str, progress=None) -> DecodedTrack:
    """Unpack *path* to a playable audio file and return its tags.

    Returns a `DecodedTrack` whose `error` is set (and `path` empty) when the
    file cannot be decoded, so callers never end up playing a half-written
    file. A second call for the same source reuses the cached result.
    """
    try:
        container = _parse(path)
    except Exception as exc:
        return DecodedTrack(error=_describe(exc))

    artist = ""
    entries = container.meta.get("artist")
    if isinstance(entries, list) and entries:
        first = entries[0]
        artist = first[0] if isinstance(first, (list, tuple)) and first else str(first or "")

    result = DecodedTrack(
        title=str(container.meta.get("musicName") or ""),
        artist=artist,
        album=str(container.meta.get("album") or ""),
        duration_ms=int(container.meta.get("duration") or 0),
        bitrate=int(container.meta.get("bitrate") or 0),
        audio_format=container.format_hint,
        cover_data=container.cover,
    )

    try:
        with open(path, "rb") as handle:
            handle.seek(container.audio_offset)
            keystream = _Keystream(container.key)
            # Sniff the format from the first chunk, then write the rest of the
            # stream with the same rotation so the keystream phase stays true.
            head = handle.read(1 << 16)
            decrypted = keystream.apply(head, 0)
            # A previous session may already have unpacked this exact file.
            # The extension is only known after sniffing, so look for either.
            for candidate_ext in (".flac", ".mp3"):
                cached = _cache_path(path, candidate_ext)
                if _cached_ok(cached):
                    result.path = cached
                    return result
            ext, skip = _sniff_format(decrypted, container.format_hint)
            if not ext:
                return DecodedTrack(error="无法识别的音频格式（可能不是标准 ncm）")
            out_path = _cache_path(path, ext)
            with open(out_path, "wb") as out:
                out.write(decrypted[skip:])
                position = len(head)
                while True:
                    chunk = handle.read(1 << 20)
                    if not chunk:
                        break
                    out.write(keystream.apply(chunk, position))
                    position += len(chunk)
                    if progress is not None:
                        progress(position)
        valid = os.path.getsize(out_path) >= 1024 and _looks_like_audio(out_path)
        if not valid:
            # Never leave an unvalidated file behind: a cached bad decode would
            # otherwise be reused and played.
            for stale in (out_path, out_path + _OK_SUFFIX):
                try:
                    os.remove(stale)
                    # Another process may have taken it; the sweep continues.
                except OSError:
                    pass
            return DecodedTrack(
                error="音频层无法解密（可能是新版客户端下载的 ncm 变体）"
            )
        _mark_ok(out_path)
        result.path = out_path
    except Exception as exc:
        return DecodedTrack(error=_describe(exc))
    return result


def _describe(exc: Exception) -> str:
    text = str(exc)
    return text if text else exc.__class__.__name__


def cover_pixmap(data: bytes):
    """QPixmap from raw cover bytes, or None. The Qt import is lazy so this
    module stays importable without Qt."""
    if not data:
        return None
    try:
        from PySide6.QtGui import QPixmap

        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            return pixmap
        # No Qt, or an undecodable image: the caller
        # treats a missing cover as no cover.
    except Exception:
        pass
    return None
