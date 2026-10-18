# SPDX-License-Identifier: AGPL-3.0-only
"""The background music: a picked file turned into the track the browser
loops, and the card's copy of it."""

from __future__ import annotations

import array
import contextlib
import io
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from tests.test_fetch import Log
from tests.test_sleekmenu_prep import stay_offline
from tools import card_layout, music, sleekmenu_prep

ROOT = Path(__file__).resolve().parent.parent


def tone(count: int, channels: int = 1, step: float = 0.05, level: int = 8000) -> array.array:
    """Interleaved 16-bit samples: a sine on the first channel, the others
    its negative halves, so a mix of them is predictable."""
    samples = array.array("h")
    for index in range(count):
        value = int(level * math.sin(index * step))
        samples.append(value)
        for _ in range(channels - 1):
            samples.append(-value // 2)
    return samples


def riff(fmt: bytes, data: bytes, extra: bytes = b"") -> bytes:
    """A RIFF WAVE file from its fmt and data chunks, with anything else
    in between."""
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt + (b"\0" if len(fmt) & 1 else b"")
    chunks += extra
    chunks += b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def fmt_chunk(tag: int, channels: int, rate: int, bits: int, extensible_of: int | None = None) -> bytes:
    block = channels * bits // 8
    head = struct.pack("<HHIIHH", 0xFFFE if extensible_of else tag, channels, rate, rate * block, block, bits)
    if extensible_of:
        guid = struct.pack("<H", extensible_of) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        head += struct.pack("<HHI", 22, bits, 0) + guid
    return head


def little(samples: array.array) -> bytes:
    copy = array.array(samples.typecode, samples)
    if sys.byteorder == "big":
        copy.byteswap()
    return copy.tobytes()


class ReadWavTests(unittest.TestCase):
    def test_sixteen_bit_mono_is_taken_as_it_is(self):
        samples = tone(1000)
        track = music.read_wav(riff(fmt_chunk(1, 1, 22050, 16), little(samples)))
        self.assertEqual((track.rate, list(track.samples)), (22050, list(samples)))

    def test_stereo_is_mixed_to_one_channel(self):
        samples = tone(1000, channels=2)
        track = music.read_wav(riff(fmt_chunk(1, 2, 32000, 16), little(samples)))
        self.assertEqual(len(track.samples), 1000)
        self.assertEqual(track.samples[10], (samples[20] + samples[21]) >> 1)

    def test_more_channels_are_averaged(self):
        samples = tone(500, channels=6)
        track = music.read_wav(riff(fmt_chunk(1, 6, 48000, 16), little(samples)))
        self.assertEqual(len(track.samples), 500)
        self.assertEqual(track.samples[7], sum(samples[42:48]) // 6)

    def test_other_sample_widths_become_sixteen_bits(self):
        samples = tone(300)
        # eight bits: unsigned, so 128 is silence
        eight = bytes((value >> 8) + 128 for value in samples)
        track = music.read_wav(riff(fmt_chunk(1, 1, 16000, 8), eight))
        self.assertEqual(list(track.samples), [(value >> 8) << 8 for value in samples])
        # 24 and 32 bits: the top two bytes
        for bits in (24, 32):
            width = bits // 8
            data = b"".join(struct.pack("<i", value << 16)[4 - width:] if width == 3
                            else struct.pack("<i", value << 16) for value in samples)
            if width == 3:
                data = b"".join(struct.pack("<i", value << 8)[:3] for value in samples)
            track = music.read_wav(riff(fmt_chunk(1, 1, 16000, bits), data))
            self.assertEqual(list(track.samples), list(samples), bits)
        # floating point, clipped at full scale
        floats = array.array("f", [0.0, 0.5, -0.5, 1.0, -1.0, 2.0, -3.0])
        track = music.read_wav(riff(fmt_chunk(3, 1, 16000, 32), little(floats)))
        self.assertEqual(list(track.samples), [0, 16383, -16383, 32767, -32768, 32767, -32768])

    def test_the_extensible_header_says_its_format_inside(self):
        samples = tone(200, channels=2)
        track = music.read_wav(riff(fmt_chunk(1, 2, 44100, 16, extensible_of=1), little(samples)))
        self.assertEqual(len(track.samples), 200)
        with self.assertRaisesRegex(music.MusicError, "compressed"):
            music.read_wav(riff(fmt_chunk(1, 2, 44100, 16, extensible_of=2), little(samples)))

    def test_chunks_it_does_not_need_are_stepped_over(self):
        samples = tone(100)
        odd = b"LIST" + struct.pack("<I", 3) + b"abc" + b"\0"
        track = music.read_wav(riff(fmt_chunk(1, 1, 22050, 16), little(samples), extra=odd))
        self.assertEqual(list(track.samples), list(samples))

    def test_a_data_chunk_longer_than_the_file_is_cut_to_it(self):
        samples = tone(100)
        data = riff(fmt_chunk(1, 1, 22050, 16), little(samples))
        at = data.index(b"data") + 4
        data = data[:at] + struct.pack("<I", 0xFFFFFFFF) + data[at + 4:]
        self.assertEqual(len(music.read_wav(data).samples), 100)

    def test_a_rate_above_48_khz_is_halved(self):
        samples = tone(1000)
        track = music.read_wav(riff(fmt_chunk(1, 1, 96000, 16), little(samples)))
        self.assertEqual((track.rate, len(track.samples)), (48000, 500))
        self.assertEqual(track.samples[3], (samples[6] + samples[7]) >> 1)
        self.assertEqual(music.read_wav(riff(fmt_chunk(1, 1, 192000, 16), little(samples))).rate, 48000)
        self.assertEqual(music.read_wav(riff(fmt_chunk(1, 1, 48000, 16), little(samples))).rate, 48000)

    def test_files_it_cannot_read_are_said_plainly(self):
        for data, said in ((b"", "isn't a WAV"), (b"ID3\x04" + bytes(100), "isn't a WAV"),
                           (riff(fmt_chunk(1, 1, 22050, 16), b"")[:-8], "no sound"),
                           (riff(fmt_chunk(2, 1, 22050, 4), bytes(100)), "compressed"),
                           (riff(fmt_chunk(1, 1, 22050, 12), bytes(100)), "kind of sample"),
                           (riff(fmt_chunk(3, 1, 22050, 16), bytes(100)), "kind of sample")):
            with self.subTest(said=said), self.assertRaisesRegex(music.MusicError, said):
                music.read_wav(data)


class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def wav(self, name: str, seconds: float, rate: int = 22050, channels: int = 1) -> Path:
        path = self.folder / name
        with wave.open(str(path), "wb") as file:
            file.setnchannels(channels)
            file.setsampwidth(2)
            file.setframerate(rate)
            file.writeframes(little(tone(int(seconds * rate), channels)))
        return path

    def test_a_wav_file_keeps_its_rate(self):
        track = music.decode(self.wav("song.wav", 2, rate=44100, channels=2))
        self.assertEqual((track.rate, len(track.samples)), (44100, 88200))
        self.assertAlmostEqual(music.probe(self.folder / "song.wav"), 2.0)

    def test_too_short_too_long_or_too_low(self):
        with self.assertRaisesRegex(music.MusicError, "shorter than a second"):
            music.decode(self.wav("blip.wav", 0.5))
        with self.assertRaisesRegex(music.MusicError, "too low quality"):
            music.decode(self.wav("phone.wav", 2, rate=4000))
        with mock.patch.object(music, "MAX_SECONDS", 1), \
                self.assertRaisesRegex(music.MusicError, "longer than 0 minutes"):
            music.decode(self.wav("long.wav", 2))

    def test_without_a_decoder_only_wav_files_are_read(self):
        mp3 = self.folder / "song.mp3"
        mp3.write_bytes(b"ID3\x04" + bytes(1000))
        with no_decoders():
            self.assertFalse(music.decoder_available())
            with self.assertRaisesRegex(music.MusicError, "install the miniaudio package .* or ffmpeg"):
                music.decode(mp3)
            with self.assertRaisesRegex(music.MusicError, "install the miniaudio package"):
                music.probe(mp3)
            # a file that is not a WAV, whatever its name says
            (self.folder / "fake.wav").write_bytes(b"not a wav")
            with self.assertRaisesRegex(music.MusicError, "isn't a WAV"):
                music.decode(self.folder / "fake.wav")
            self.assertEqual(music.decode(self.wav("fine.wav", 1.5)).rate, 22050)
            # a WAV is a WAV whatever its name says, too
            self.wav("song.mp3", 1.5)
            self.assertEqual(music.decode(mp3).rate, 22050)

    def test_the_chooser_offers_every_kind_of_song(self):
        for suffix in (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aiff"):
            self.assertIn(suffix, music.SUFFIXES)

    def test_a_file_that_is_not_there(self):
        with self.assertRaisesRegex(music.MusicError, "can't be opened"):
            music.decode(self.folder / "gone.wav")
        with self.assertRaisesRegex(music.MusicError, "can't be opened"):
            music.decode(self.folder / "gone.mp3")


def no_decoders():
    """This computer, as one with nothing to read an MP3 with."""
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(music, "_miniaudio", return_value=None))
    stack.enter_context(mock.patch.object(music, "_converters", return_value=[]))
    return stack


def ulaw_wav(path: Path, seconds: float, rate: int = 44100, channels: int = 2) -> Path:
    """A WAV of G.711 mu-law samples: compressed, so this module does not
    read it, and every decoder does."""
    def encode(sample: int) -> int:
        sign = 0x80 if sample < 0 else 0
        sample = min(abs(sample), 32635) + 0x84
        exponent, mask = 7, 0x4000
        while exponent and not sample & mask:
            exponent, mask = exponent - 1, mask >> 1
        return ~(sign | exponent << 4 | (sample >> (exponent + 3)) & 0x0F) & 0xFF
    data = bytes(encode(value) for value in tone(int(seconds * rate), channels))
    path.write_bytes(riff(struct.pack("<HHIIHH", 7, channels, rate, rate * channels, channels, 8), data))
    return path


@unittest.skipUnless(music._miniaudio() is not None, "miniaudio is not installed")
class MiniaudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_decoded_file_is_brought_to_32_khz_mono(self):
        path = ulaw_wav(self.folder / "song.wav", 2)
        with mock.patch.object(music, "_converters", return_value=[]):
            track = music.decode(path)
        self.assertEqual(track.rate, music.DECODED_RATE)
        self.assertAlmostEqual(track.seconds, 2.0, delta=0.01)
        self.assertEqual(music.decoders()[0], "miniaudio")

    def test_a_file_no_decoder_can_read(self):
        path = self.folder / "song.mp3"
        path.write_bytes(bytes(5000))
        with mock.patch.object(music, "_converters", return_value=[]):
            with self.assertRaisesRegex(music.MusicError, "can't be read"):
                music.decode(path)
            with self.assertRaisesRegex(music.MusicError, "can't be read"):
                music.probe(path)


class ConverterTests(unittest.TestCase):
    """afconvert on a Mac and ffmpeg anywhere, for a computer without
    miniaudio: the downloadable archive run by a Python that has none."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        patch = mock.patch.object(music, "_miniaudio", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def fake_afconvert(self, works: bool = True) -> Path:
        """An afconvert that writes a 32 kHz stereo WAV and notes how it was
        called, on a PATH of its own."""
        bin_dir = self.folder / "bin"
        bin_dir.mkdir()
        made = bin_dir / "song.wav"
        with wave.open(str(made), "wb") as file:
            file.setnchannels(2)
            file.setsampwidth(2)
            file.setframerate(32000)
            file.writeframes(little(tone(64000, 2)))
        tool = bin_dir / "afconvert"
        tool.write_text(
            f"#!{sys.executable}\n"
            "import shutil, sys\n"
            f"open({str(bin_dir / 'called')!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
            + (f"shutil.copy({str(made)!r}, sys.argv[-1])\n" if works else "sys.exit(1)\n"),
            encoding="utf-8")
        tool.chmod(0o755)
        return bin_dir

    def test_a_mac_reads_other_songs_with_afconvert(self):
        bin_dir = self.fake_afconvert()
        song = self.folder / "Title Theme.mp3"
        song.write_bytes(b"ID3\x04" + bytes(1000))
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.dict(os.environ, {"PATH": str(bin_dir)}), \
                mock.patch.object(music, "FFMPEG_PLACES", ()):
            self.assertEqual(music.decoders(), ["afconvert"])
            track = music.decode(song)
            self.assertAlmostEqual(music.probe(song), 2.0)
        self.assertEqual((track.rate, len(track.samples)), (32000, 64000))
        called = (bin_dir / "called").read_text().split("\n")
        self.assertEqual(called[:4], ["-f", "WAVE", "-d", "LEI16@32000"])
        self.assertEqual(called[4], str(song))
        self.assertTrue(called[5].endswith(".wav"))

    def test_afconvert_is_only_a_macs(self):
        bin_dir = self.fake_afconvert()
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.dict(os.environ, {"PATH": str(bin_dir)}), \
                mock.patch.object(music, "FFMPEG_PLACES", ()):
            self.assertEqual(music.decoders(), [])

    def test_a_converter_that_fails_is_said_plainly(self):
        bin_dir = self.fake_afconvert(works=False)
        song = self.folder / "song.ogg"
        song.write_bytes(b"OggS" + bytes(1000))
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.dict(os.environ, {"PATH": str(bin_dir)}), \
                mock.patch.object(music, "FFMPEG_PLACES", ()):
            with self.assertRaisesRegex(music.MusicError, "can't be read. Pick an MP3"):
                music.decode(song)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_ffmpeg_reads_what_this_module_does_not(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(music.decoders(), ["ffmpeg"])
            track = music.decode(ulaw_wav(self.folder / "song.wav", 2))
            self.assertEqual(track.rate, music.DECODED_RATE)
            self.assertAlmostEqual(track.seconds, 2.0, delta=0.02)
            # and a FLAC, which ffmpeg also writes
            flac = self.folder / "song.flac"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(self.folder / "song.wav"),
                            str(flac)], check=True)
            self.assertAlmostEqual(music.probe(flac), 2.0, delta=0.02)


class CardTests(unittest.TestCase):
    def setUp(self):
        stay_offline(self)
        self.temporary = tempfile.TemporaryDirectory()
        self.card = Path(self.temporary.name) / "CARD"
        self.card.mkdir()
        self.song = Path(self.temporary.name) / "Title Theme.wav"
        with wave.open(str(self.song), "wb") as file:
            file.setnchannels(2)
            file.setsampwidth(2)
            file.setframerate(22050)
            file.writeframes(little(tone(22050 * 3, 2)))

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_names_agree_with_the_console(self):
        header = (ROOT / "src" / "card_paths.h").read_text(encoding="utf-8")
        self.assertIn(f'#define SM_MUSIC_PATH SM_CARD_DIR "/{card_layout.MUSIC_FILE}"', header)
        self.assertIn(f'#define SM_MUSIC_SETTING_PATH SM_CARD_DIR "/{card_layout.MUSIC_SETTING_FILE}"', header)
        self.assertEqual(music.track_path(self.card), self.card / "sleekmenu" / "music.wav64")

    def test_the_file_is_wav64_with_big_endian_samples_looped_whole(self):
        track = music.Track(22050, array.array("h", [1, -2, 300, -32768]))
        data = music.encode(track, "Title Theme.wav")
        magic, version, kind, channels, bits, rate, count, loop, start = struct.unpack(">4sbbbbiiii", data[:24])
        self.assertEqual((magic, version, kind, channels, bits), (b"WV64", 2, 0, 1, 16))
        self.assertEqual((rate, count, loop), (22050, 4, 4))
        self.assertEqual(start % 16, 0)
        self.assertEqual(data[24:28], b"name")
        self.assertEqual(data[29:29 + data[28]], b"Title Theme.wav")
        self.assertEqual(data[start:], struct.pack(">4h", 1, -2, 300, -32768))
        self.assertEqual(len(data), start + 8)
        # a name too long for its byte is cut
        self.assertEqual(music.encode(track, "x" * 400)[28], 255)

    def test_the_console_reads_what_the_tool_writes(self):
        """src/music.c's header check, on a file this module wrote."""
        music.sync(self.card, self.song)
        probe = Path(self.temporary.name) / "probe.c"
        probe.write_text(
            '#include "music.h"\n#include <stdio.h>\n'
            "int main(int argc, char **argv) {\n"
            "    unsigned char head[24]; sm_music_info_t info; long size;\n"
            "    if (argc < 2) return 3;\n"
            "    FILE *file = fopen(argv[1], \"rb\");\n"
            "    if (!file || fread(head, 1, 24, file) != 24) return 2;\n"
            "    fseek(file, 0, SEEK_END); size = ftell(file); fclose(file);\n"
            "    if (!sm_music_read_header(head, 24, (uint32_t)size, &info)) return 1;\n"
            "    printf(\"%u %u %u\\n\", (unsigned)info.frequency, (unsigned)info.samples,\n"
            "        (unsigned)info.data_offset);\n"
            "    return 0;\n}\n", encoding="utf-8")
        binary = Path(self.temporary.name) / "probe"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Isrc", "-Itests/stubs",
                        "src/music.c", "tests/stubs/libdragon_stub.c", str(probe), "-o", str(binary)],
                       cwd=ROOT, check=True)
        said = subprocess.run([str(binary), str(music.track_path(self.card))], capture_output=True,
                              text=True, check=True).stdout.split()
        data = music.track_path(self.card).read_bytes()
        self.assertEqual(said, ["22050", str(22050 * 3), str(struct.unpack(">i", data[20:24])[0])])

    def test_sync_puts_the_song_on_and_takes_it_off(self):
        log = Log()
        self.assertIsNone(music.read_card(self.card))
        self.assertIsNone(music.sync(self.card, None, log=log))
        self.assertEqual(log.text(), "", "told nothing, nothing happens")
        # the console had the last song off: a new song is heard
        music.setting_path(self.card).parent.mkdir(parents=True)
        music.setting_path(self.card).write_bytes(b"off\n")
        on_card = music.sync(self.card, self.song, log=log)
        self.assertEqual((on_card.name, round(on_card.seconds, 3)), ("Title Theme.wav", 3.0))
        self.assertFalse(music.setting_path(self.card).exists())
        self.assertIn("music:    Title Theme.wav, 0:03, 22050 Hz mono", log.text())
        self.assertEqual(music.read_card(self.card), on_card)
        self.assertEqual(sorted(p.name for p in music.track_path(self.card).parent.iterdir()), ["music.wav64"])
        # off again, with the console's setting
        music.setting_path(self.card).write_bytes(b"off\n")
        log = Log()
        self.assertIsNone(music.sync(self.card, None, remove=True, log=log))
        self.assertFalse(music.track_path(self.card).exists())
        self.assertFalse(music.setting_path(self.card).exists())
        self.assertIn("music:    removed", log.text())
        log = Log()
        music.sync(self.card, None, remove=True, log=log)
        self.assertEqual(log.text(), "", "nothing to remove")

    def test_a_song_that_cannot_be_read_leaves_the_card_as_it_was(self):
        music.sync(self.card, self.song)
        before = music.track_path(self.card).read_bytes()
        bad = Path(self.temporary.name) / "bad.wav"
        bad.write_bytes(b"junk")
        with self.assertRaises(music.MusicError):
            music.sync(self.card, bad)
        self.assertEqual(music.track_path(self.card).read_bytes(), before)
        self.assertFalse(music.track_path(self.card).with_name("music.wav64.part").exists())

    def test_the_card_is_read_as_the_console_would(self):
        music.sync(self.card, self.song)
        target = music.track_path(self.card)
        good = target.read_bytes()
        for broken in (good[:20], b"WV64" + bytes([2, 1, 1, 16]) + good[8:], b"RIFF" + good[4:],
                       good[:5] + b"\x00\x02" + good[7:]):
            target.write_bytes(broken)
            self.assertIsNone(music.read_card(self.card))
        # cut short: what is there
        target.write_bytes(good[:len(good) - 22050 * 2])
        self.assertAlmostEqual(music.read_card(self.card).seconds, 2.0)
        self.assertIsNone(music.read_card(None))

    def test_a_run_puts_the_song_on_the_card_and_a_dry_run_does_not(self):
        with contextlib.redirect_stdout(io.StringIO()):
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, music=self.song, dry_run=True),
                               log=log, fail=log)
            self.assertFalse(music.track_path(self.card).exists())
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, music=self.song), log=log, fail=log)
            self.assertEqual(code, 0, log.text())
            self.assertEqual(music.read_card(self.card).name, "Title Theme.wav")
            log = Log()
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card), log=log, fail=log)
            self.assertNotIn("music:", log.text(), "a run told nothing leaves the card's song")
            self.assertTrue(music.track_path(self.card).exists())
            # a song that can't be used is said, and the run still ends well
            bad = Path(self.temporary.name) / "bad.wav"
            bad.write_bytes(b"junk")
            outcome = sleekmenu_prep.Outcome()
            log = Log()
            code = sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, music=bad), log=log, fail=log,
                                      outcome=outcome)
            self.assertEqual(code, 0)
            # what is said depends on whether miniaudio had a go at it too
            said = "This file can't be read" if music.decoder_available() else "This isn't a WAV file."
            self.assertIn(f"music:    not changed ({said}", log.text())
            self.assertTrue(outcome.music_failure.startswith(said))
            self.assertEqual(music.read_card(self.card).name, "Title Theme.wav")
            sleekmenu_prep.run(sleekmenu_prep.Options(card=self.card, no_music=True), log=log, fail=log)
            self.assertFalse(music.track_path(self.card).exists())

    def test_the_command_line(self):
        with mock.patch.object(sleekmenu_prep, "run", return_value=0) as run:
            sleekmenu_prep.main(["--card", str(self.card), "--music", str(self.song)])
            self.assertEqual((run.call_args.args[0].music, run.call_args.args[0].no_music), (self.song, False))
            sleekmenu_prep.main(["--card", str(self.card), "--no-music"])
            self.assertEqual((run.call_args.args[0].music, run.call_args.args[0].no_music), (None, True))
            sleekmenu_prep.main(["--card", str(self.card)])
            self.assertEqual((run.call_args.args[0].music, run.call_args.args[0].no_music), (None, False))

    def test_the_song_is_never_a_game(self):
        from tools import library
        from tests.rom_fixtures import write_rom
        write_rom(self.card / "ROMS" / "Wave Race 64 (USA).z64", 0x11, 0x22, game_code="WR")
        music.sync(self.card, self.song)
        self.assertEqual(library.walk(self.card), ["ROMS/Wave Race 64 (USA).z64"])

    def test_durations_are_said_like_a_music_player(self):
        self.assertEqual([music.duration(s) for s in (0, 3, 59.6, 187, 3600)], ["0:00", "0:03", "1:00", "3:07", "60:00"])


if __name__ == "__main__":
    unittest.main()
