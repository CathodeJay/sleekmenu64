# SPDX-License-Identifier: AGPL-3.0-only
"""Background music: one track the browser loops while it runs.

The browser plays

    sleekmenu/music.wav64

a WAV64 file, libdragon's audio container, holding plain 16-bit mono
samples. Nothing is decoded on the console: the samples are streamed off
the card a few kilobytes at a time and handed to the mixer as they are, so
the file is as simple as the console can play. This module writes it from
the track the card owner picks.

A WAV file is read here, by the standard library alone, and keeps its own
sample rate (one above 48 kHz is halved until it is not). Anything else --
MP3, M4A, FLAC, OGG, AIFF -- goes through the first decoder this computer
has that reads it: the optional `miniaudio` package, which the downloadable
builds carry; afconvert, which comes with macOS; or ffmpeg. Each brings
the track to 32 kHz. Either way the channels are mixed down to one, which
is half the reading a stereo track would cost the cartridge while the
browser draws.

Whether the music plays is the console's choice, made on its filter page
and kept in sleekmenu/music.txt. A new track clears that file, so the music
someone just picked is heard.

The header records the name of the file the track came from, between the
fields libdragon reads and the first sample (WAV64's start offset says
where the samples start), so the window can say which song is on the card.
"""

from __future__ import annotations

import array
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import card_layout

#: The rates the console takes (src/music.h has the same).
MIN_RATE = 8000
MAX_RATE = 48000
#: What a decoded MP3, FLAC, OGG... is brought to.
DECODED_RATE = 32000
#: Longer than this is not background music, and would cost the card a
#: lot of room for nothing: an hour at 32 kHz is 230 MB.
MAX_SECONDS = 30 * 60

#: The suffixes the window's chooser offers. WAV is always read; the others
#: by whichever decoder the computer has (decoders()).
WAV_SUFFIXES = (".wav", ".wave")
OTHER_SUFFIXES = (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".aif", ".aiff")
SUFFIXES = WAV_SUFFIXES + OTHER_SUFFIXES
#: Where ffmpeg usually is when a program started from the Finder or the
#: Start menu was not given the shell's PATH.
FFMPEG_PLACES = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")
#: The longest a converter may take over one song.
CONVERT_SECONDS = 300

_HEADER = struct.Struct(">4sbbbbiiii")      # WAV64 version 2, as libdragon reads it
_NAME_TAG = b"name"


class MusicError(Exception):
    """A track that cannot go on the card, said the way the window says it."""


@dataclass(frozen=True)
class Track:
    rate: int
    samples: array.array        # signed 16-bit, mono, in this machine's byte order

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate if self.rate else 0.0


@dataclass(frozen=True)
class OnCard:
    """What the card holds: where the track came from and how long it is."""
    name: str
    seconds: float
    size: int


def track_path(card: Path) -> Path:
    return card / card_layout.CARD_FOLDER / card_layout.MUSIC_FILE


def setting_path(card: Path) -> Path:
    return card / card_layout.CARD_FOLDER / card_layout.MUSIC_SETTING_FILE


def _miniaudio():
    try:
        import miniaudio
    except ImportError:
        return None
    return miniaudio


def _converters() -> list:
    """The audio converters on this computer, as (name, command for a
    source and a WAV to write): afconvert on a Mac, then ffmpeg."""
    found = []
    if sys.platform == "darwin":
        tool = shutil.which("afconvert") or shutil.which("afconvert", path="/usr/bin")
        if tool:
            # 16-bit little-endian WAV at the decoded rate. Its -c drops
            # channels rather than mixing them, so read_wav mixes.
            found.append(("afconvert", lambda source, out, tool=tool: [
                tool, "-f", "WAVE", "-d", f"LEI16@{DECODED_RATE}", str(source), str(out)]))
    tool = shutil.which("ffmpeg") or shutil.which("ffmpeg", path=os.pathsep.join(FFMPEG_PLACES))
    if tool:
        found.append(("ffmpeg", lambda source, out, tool=tool: [
            tool, "-nostdin", "-v", "error", "-y", "-i", str(source), "-vn", "-ac", "1",
            "-ar", str(DECODED_RATE), "-c:a", "pcm_s16le", "-f", "wav", str(out)]))
    return found


def decoders() -> list:
    """The names of what this computer can read songs other than WAV with,
    best first."""
    return (["miniaudio"] if _miniaudio() else []) + [name for name, _ in _converters()]


def decoder_available() -> bool:
    return bool(decoders())


def duration(seconds: float) -> str:
    """3:07, the way a music player says it."""
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


# -- reading the picked file -------------------------------------------------

def _mono(samples: array.array, channels: int) -> array.array:
    if channels == 1:
        return samples
    if channels == 2:
        return array.array("h", [(a + b) >> 1 for a, b in zip(samples[0::2], samples[1::2])])
    lanes = [samples[lane::channels] for lane in range(channels)]
    return array.array("h", [sum(frame) // channels for frame in zip(*lanes)])


def _from_little16(data: bytes) -> array.array:
    samples = array.array("h")
    samples.frombytes(data[:len(data) - len(data) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _pcm16(data: bytes, bits: int, is_float: bool) -> array.array:
    """Little-endian samples of any common width, as 16-bit ones: the top
    two bytes of each wider sample, eight-bit ones moved to signed."""
    if is_float:
        code = {32: "f", 64: "d"}.get(bits)
        if code is None:
            raise MusicError("This WAV file uses a kind of sample that can't be read.")
        values = array.array(code)
        width = bits // 8
        values.frombytes(data[:len(data) - len(data) % width])
        if sys.byteorder == "big":
            values.byteswap()
        return array.array("h", [32767 if v >= 1.0 else -32768 if v <= -1.0 else int(v * 32767.0)
                                 for v in values])
    if bits == 16:
        return _from_little16(data)
    if bits == 8:
        return array.array("h", [(byte - 128) << 8 for byte in data])
    if bits in (24, 32):
        width = bits // 8
        count = len(data) // width
        top = bytearray(count * 2)
        top[0::2] = data[width - 2:count * width:width]
        top[1::2] = data[width - 1:count * width:width]
        return _from_little16(bytes(top))
    raise MusicError("This WAV file uses a kind of sample that can't be read.")


def read_wav(data: bytes) -> Track:
    """A RIFF WAVE file's samples, mixed to mono, at the file's own rate
    (halved while above MAX_RATE)."""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise MusicError("This isn't a WAV file.")
    at = 12
    fmt = None
    samples = None
    while at + 8 <= len(data):
        kind, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
        body = data[at + 8:at + 8 + size]           # a data chunk that claims more than the file is cut
        if kind == b"fmt " and len(body) >= 16:
            fmt = body
        elif kind == b"data":
            samples = body
            if fmt is not None:
                break
        at += 8 + size + (size & 1)
    if fmt is None or samples is None:
        raise MusicError("This WAV file has no sound in it.")
    tag, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", fmt)
    if tag == 0xFFFE and len(fmt) >= 26:
        tag = struct.unpack_from("<H", fmt, 24)[0]  # WAVE_FORMAT_EXTENSIBLE: the real format leads the GUID
    if tag not in (1, 3) or not channels or not rate:
        raise MusicError("This WAV file is compressed in a way that can't be read. Save it as plain PCM.")
    mono = _mono(_pcm16(samples, bits, tag == 3), channels)
    while rate > MAX_RATE:
        mono = array.array("h", [(a + b) >> 1 for a, b in zip(mono[0::2], mono[1::2])])
        rate //= 2
    return Track(rate, mono)


NO_DECODER = ("To use MP3, FLAC or OGG files, install the miniaudio package (pip3 install miniaudio) "
              "or ffmpeg. WAV files always work.")
UNREADABLE = "This file can't be read. Pick an MP3, FLAC, OGG or WAV file."


def _decoded(source: Path) -> Track:
    """Anything but a plain WAV, through the first decoder that reads it."""
    miniaudio = _miniaudio()
    if miniaudio is not None:
        try:
            decoded = miniaudio.decode_file(str(source), output_format=miniaudio.SampleFormat.SIGNED16,
                                            nchannels=1, sample_rate=DECODED_RATE)
            return Track(DECODED_RATE, array.array("h", decoded.samples))
        except miniaudio.MiniaudioError:
            pass                    # an M4A or an AIFF, which miniaudio does not read
    converters = _converters()
    for _name, command in converters:
        with tempfile.TemporaryDirectory(prefix="sleekmenu-music-") as work:
            out = Path(work) / "song.wav"
            try:
                subprocess.run(command(source, out), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=CONVERT_SECONDS, check=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return read_wav(out.read_bytes())
            except (OSError, subprocess.SubprocessError, MusicError):
                continue
    if miniaudio is None and not converters:
        raise MusicError(NO_DECODER)
    raise MusicError(UNREADABLE)


def _is_wav(source: Path) -> bool:
    try:
        with source.open("rb") as file:
            head = file.read(12)
    except OSError as error:
        raise MusicError(f"This file can't be opened ({error.strerror or error}).") from None
    return head[0:4] == b"RIFF" and head[8:12] == b"WAVE"


def decode(source: Path) -> Track:
    """The picked file as a track the console can play."""
    if _is_wav(source) or (source.suffix.lower() in WAV_SUFFIXES and not decoder_available()):
        try:
            track = read_wav(source.read_bytes())
        except OSError as error:
            raise MusicError(f"This file can't be opened ({error.strerror or error}).") from None
        except MusicError:
            # A WAV compressed in a way this module does not read, which a
            # decoder may.
            if not decoder_available():
                raise
            track = _decoded(source)
    else:
        track = _decoded(source)
    if track.rate < MIN_RATE:
        raise MusicError("The sound in this file is too low quality to play. Pick another one.")
    if track.seconds < 1:
        raise MusicError("This file is shorter than a second.")
    if track.seconds > MAX_SECONDS:
        raise MusicError(f"This file is longer than {MAX_SECONDS // 60} minutes. Pick a shorter one.")
    return track


def probe(source: Path) -> float:
    """How long the picked file plays, read quickly, for the window to show
    before anything is converted. Raises MusicError for a file this tool
    can't read."""
    miniaudio = None if _is_wav(source) else _miniaudio()
    if miniaudio is None:
        # A WAV is read in a moment; a converter has to convert the whole
        # song, a second or two.
        return decode(source).seconds
    try:
        seconds = float(miniaudio.get_file_info(str(source)).duration)
    except miniaudio.MiniaudioError:
        # The quick look goes by the file's name; decoding tries every
        # format and every decoder.
        return decode(source).seconds
    if seconds > MAX_SECONDS:
        raise MusicError(f"This file is longer than {MAX_SECONDS // 60} minutes. Pick a shorter one.")
    if seconds < 1:
        raise MusicError("This file is shorter than a second.")
    return seconds


# -- the file on the card ----------------------------------------------------

def encode(track: Track, name: str = "") -> bytes:
    """WAV64 version 2, raw 16-bit mono samples, looped whole. The source's
    name sits between the header and the samples, padded so they start on
    a 16-byte boundary."""
    label = name.encode("utf-8")[:255]
    note = _NAME_TAG + bytes([len(label)]) + label
    start = _HEADER.size + len(note)
    start += -start % 16
    count = len(track.samples)
    head = _HEADER.pack(b"WV64", 2, 0, 1, 16, track.rate, count, count, start)
    big = array.array("h", track.samples)
    if sys.byteorder == "little":
        big.byteswap()
    return head + note + bytes(start - _HEADER.size - len(note)) + big.tobytes()


def read_card(card: Path | None) -> OnCard | None:
    """The track on the card, or None when there is none the browser would
    play."""
    if card is None:
        return None
    target = track_path(card)
    try:
        size = target.stat().st_size
        with target.open("rb") as file:
            head = file.read(_HEADER.size + 5 + 255)
    except OSError:
        return None
    if len(head) < _HEADER.size:
        return None
    magic, version_, kind, channels, bits, rate, count, _, start = _HEADER.unpack_from(head)
    if magic != b"WV64" or version_ != 2 or kind != 0 or channels != 1 or bits != 16:
        return None
    if not MIN_RATE <= rate <= MAX_RATE or start < _HEADER.size or start >= size:
        return None
    count = min(count, (size - start) // 2)
    name = ""
    note = head[_HEADER.size:start]
    if note[:4] == _NAME_TAG and len(note) >= 5:
        name = note[5:5 + note[4]].decode("utf-8", "replace")
    return OnCard(name, count / rate, size)


def write(card: Path, track: Track, name: str) -> Path:
    target = track_path(card)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(encode(track, name))
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()
    return target


def sync(card: Path, source: Path | None, remove: bool = False, log=None) -> OnCard | None:
    """Put `source` on the card as its music, or take the music off with
    `remove`, or leave the card as it is when told neither."""
    say = log or (lambda _line: None)
    if remove:
        removed = False
        for target in (track_path(card), setting_path(card)):
            if target.exists():
                target.unlink()
                removed = True
        if removed:
            say("music:    removed")
        return None
    if source is None:
        return read_card(card)
    track = decode(source)
    write(card, track, source.name)
    # Turned off on the console for the last song is not a choice about
    # this one.
    if setting_path(card).exists():
        setting_path(card).unlink()
    on_card = read_card(card)
    say(f"music:    {source.name}, {duration(track.seconds)}, {track.rate} Hz mono"
        + (f" ({on_card.size / 1048576:.1f} MB)" if on_card else ""))
    return on_card
