# Spleen 5x8 — the interface font (vendored, unmodified)

Source: https://github.com/fcambus/spleen
Tag:    2.2.0 (commit 0493c34e22791824767c618fed42c434b477662c); the file is
        byte-identical on master at 57f9219328c9f5873085320fe8bc8f7dd34b8791
Files:  spleen-5x8.bdf LICENSE

Unmodified, byte for byte; MANIFEST.sha256 pins both files and a host test
verifies it. Only the 5x8 size is carried: it is the one the browser draws
with, at 320 pixels across, and the other sizes are not used.

`tools/build_compact_font.py` reads the BDF -- one hex row per scanline, a
plain text format -- and lays the glyphs for codes 0-127 into an 80x64
atlas of 5x8 cells, sixteen across, which `tools/make_sprite.py` writes as
the libdragon sprite `graphics_draw_text` draws from. The BDF's other
glyphs (Latin-1, box drawing) are not reachable through a C `char` and are
left out. No font tool is involved, so building the ROM needs nothing
beyond Python and Pillow.

## Licence

BSD-2-Clause (see LICENSE), copyright 2018-2026 Frederic Cambus. Permissive
and compatible with the project's AGPL-3.0-only; the built ROM carries the
glyphs and this notice travels with the source.
