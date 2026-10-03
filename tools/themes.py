# SPDX-License-Identifier: AGPL-3.0-only
"""The browser's colour themes, and the card's choice of one.

A theme is a set of colours, one per role the browser draws with: the
background, the bars, the selection, each weight of text, the accent. The
themes are built into the ROM; the card says which one to use in

    sleekmenu/theme.txt

whose first word is a theme's id. The browser reads it when it starts and
falls back to the first theme for a missing file or a name it does not
know, so a card prepared by a newer tool still starts on an older ROM.

This file is where the themes are defined. `src/theme_table.h` is written
from it (`python3 -m tools.themes --header src/theme_table.h`) and checked
in, so the ROM builds without Python and a test holds the two together.
Midnight is the look the browser has always had, spelled out; the others
are the same picture in another hue: every blue of Midnight turned to the
theme's own hue, its saturation and lightness scaled, with an accent of
its own. The colours that carry a meaning rather than a mood -- a warning,
an error, the favourite star -- are the same in every theme, and so are
the controller buttons' own colours, which are not part of a theme at all.
"""

from __future__ import annotations

import argparse
import colorsys
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Runnable as a script as well as importable -- see tools/__init__.py.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import card_layout

Colour = tuple[int, int, int]

#: Every role, in the order the ROM's table holds them.
ROLES = (
    "bg",               # the screen
    "bar",              # the help bar, the tab strip, a row of the filter page
    "well",             # where a picture is missing; a scrollbar's track
    "band",             # the title band
    "tab",              # a tab that is not the current one; a folder tile
    "stripe",           # a folder's row in the list
    "select",           # the selection bar, the current tab
    "select_hi",        # the selection, one step lighter
    "thumb",            # a scrollbar's thumb
    "folder",           # the folder card on the coverflow shelf
    "text",             # what is read: titles, values
    "text_bright",      # text on the selection
    "text_body",        # a list row, a paragraph
    "text_soft",        # the help bar, a heading
    "text_muted",       # second-rank text
    "text_dim",         # labels
    "text_faint",       # an initial no game is filed under
    "accent",           # the name in the title band, folders, the selection's edge
    "accent_ink",       # text drawn on the accent
    "star",             # a favourite
    "warn",
    "error",
    "progress",         # the load bar
    "progress_verify",  # the load bar, on a verified load
    "progress_head",    # its leading edge
)

MIDNIGHT: dict[str, Colour] = {
    "bg": (8, 12, 20), "bar": (16, 22, 32), "well": (35, 42, 52), "band": (24, 45, 72),
    "tab": (30, 44, 62), "stripe": (20, 32, 48), "select": (45, 75, 110), "select_hi": (70, 95, 130),
    "thumb": (90, 120, 155), "folder": (78, 108, 150),
    "text": (240, 240, 232), "text_bright": (255, 255, 255), "text_body": (200, 208, 220),
    "text_soft": (180, 200, 220), "text_muted": (150, 165, 185), "text_dim": (110, 128, 150),
    "text_faint": (55, 64, 78),
    "accent": (245, 230, 160), "accent_ink": (20, 24, 32), "star": (250, 210, 90),
    "warn": (255, 190, 90), "error": (255, 96, 80),
    "progress": (70, 140, 200), "progress_verify": (200, 170, 70), "progress_head": (235, 245, 255),
}

#: The roles that are Midnight's blue, in one weight or another: what a
#: theme of another hue turns.
TINTED = ("bg", "bar", "well", "band", "tab", "stripe", "select", "select_hi", "thumb", "folder",
          "text_body", "text_soft", "text_muted", "text_dim", "text_faint", "accent_ink", "progress")


def tinted(hue: float, accent: Colour, saturation: float = 1.0, lightness: float = 1.0) -> dict[str, Colour]:
    """Midnight in another hue (degrees), with an accent of its own."""
    colours = dict(MIDNIGHT)
    for role in TINTED:
        red, green, blue = (channel / 255.0 for channel in MIDNIGHT[role])
        _hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
        mixed = colorsys.hls_to_rgb((hue % 360.0) / 360.0, min(1.0, light * lightness), min(1.0, sat * saturation))
        colours[role] = tuple(int(round(channel * 255.0)) for channel in mixed)   # type: ignore[assignment]
    colours["accent"] = accent
    return colours


@dataclass(frozen=True)
class Theme:
    id: str                 # what the card's file says: lower case, no spaces
    name: str               # what a person reads
    colours: dict[str, Colour]


#: The first is the default: what a card that says nothing gets.
THEMES: tuple[Theme, ...] = (
    Theme("midnight", "Midnight", MIDNIGHT),
    Theme("charcoal", "Charcoal", tinted(215, (255, 176, 80), saturation=0.12)),
    Theme("jungle", "Jungle", tinted(150, (214, 240, 130), saturation=0.95)),
    Theme("grape", "Grape", tinted(272, (255, 178, 224), saturation=0.95, lightness=1.05)),
    Theme("fire", "Fire", tinted(8, (255, 208, 96), saturation=1.05)),
    Theme("ice", "Ice", tinted(190, (190, 240, 255), saturation=1.1, lightness=1.08)),
)
DEFAULT = THEMES[0]
#: How long an id or a name may be: the ROM reads the file into a small buffer.
ID_MAX = 15


def find(theme_id: str | None) -> Theme | None:
    wanted = (theme_id or "").strip().lower()
    return next((theme for theme in THEMES if theme.id == wanted), None)


def by_name(name: str) -> Theme | None:
    return next((theme for theme in THEMES if theme.name == name), None)


# -- the card's choice ---------------------------------------------------------

def path(card: Path) -> Path:
    return card / card_layout.CARD_FOLDER / card_layout.THEME_FILE


def read(card: Path | None) -> Theme:
    """The theme the card asks for, as the browser reads it: the first word
    of the file, the default for no file or a name nobody knows."""
    if card is None:
        return DEFAULT
    try:
        words = path(card).read_text(encoding="ascii", errors="replace").split()
    except OSError:
        return DEFAULT
    return find(words[0] if words else "") or DEFAULT


def write(card: Path, theme: Theme) -> None:
    target = path(card)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        part.write_text(theme.id + "\n", encoding="ascii", newline="\n")
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()


def sync(card: Path, wanted: str | None, log=None) -> Theme:
    """Put the card on the theme the run was told (`wanted`, an id), or
    leave it alone when it was told nothing. A card that never chose has no
    file, and choosing the default does not make one."""
    if wanted is None:
        return read(card)
    theme = find(wanted)
    if theme is None:
        raise ValueError(f"no theme called {wanted!r}; there are: " + ", ".join(t.id for t in THEMES))
    if read(card) is not theme or (theme is not DEFAULT and not path(card).is_file()):
        write(card, theme)
        if log is not None:
            log(f"theme:    {theme.name}")
    return theme


# -- the ROM's table -------------------------------------------------------------

def header() -> str:
    """src/theme_table.h: the roles as an enum, and the themes as a table
    for the one file that defines SM_THEME_TABLE_DEFINE."""
    lines = [
        "/* SPDX-License-Identifier: AGPL-3.0-only */",
        "/* Written by tools/themes.py -- change the themes there, then run",
        "   python3 -m tools.themes --header src/theme_table.h */",
        "#ifndef SLEEKMENU_THEME_TABLE_H",
        "#define SLEEKMENU_THEME_TABLE_H",
        "",
        "typedef enum {",
    ]
    lines += [f"    SM_C_{role.upper()}," for role in ROLES]
    lines += [
        "    SM_C_COUNT",
        "} sm_colour_role_t;",
        "",
        f"#define SM_THEME_COUNT {len(THEMES)}u",
        f"#define SM_THEME_ID_MAX {ID_MAX}u",
        "",
        "#ifdef SM_THEME_TABLE_DEFINE",
        "static const struct {",
        "    const char *id;",
        "    const char *name;",
        "    unsigned char rgb[SM_C_COUNT][3];",
        "} SM_THEME_TABLE[SM_THEME_COUNT] = {",
    ]
    for theme in THEMES:
        lines.append(f'    {{ "{theme.id}", "{theme.name}", {{')
        for role in ROLES:
            red, green, blue = theme.colours[role]
            lines.append(f"        {{{red:3d}, {green:3d}, {blue:3d}}},  /* {role} */")
        lines.append("    } },")
    lines += ["};", "#endif", "", "#endif", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The browser's themes: list them, or write the ROM's table.")
    parser.add_argument("--header", type=Path, help="write src/theme_table.h here")
    args = parser.parse_args(argv)
    if args.header:
        args.header.write_text(header(), encoding="ascii", newline="\n")
        print(f"wrote {args.header}: {len(THEMES)} themes, {len(ROLES)} colours each")
        return 0
    for theme in THEMES:
        print(f"{theme.id:10} {theme.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
