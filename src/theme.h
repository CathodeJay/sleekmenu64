/* SPDX-License-Identifier: AGPL-3.0-only */
#ifndef SLEEKMENU_THEME_H
#define SLEEKMENU_THEME_H

/* The colours the browser draws with.

   Nothing in the browser names a colour by its numbers: it names what the
   colour is for -- the background, the selection, text on the selection --
   and the theme in use says which colour that is. The themes are built in
   (theme_table.h, written from tools/themes.py) and the card picks one by
   name in sleekmenu/theme.txt, written by the THEME row of the filter page
   and by the Game Catalog Manager alike. A card that says nothing, or names
   a theme this ROM does not have, gets the first.

   The controller buttons' colours are not here: a blue A is blue in every
   theme, because that is the colour of the button under the thumb.

   Everything but sm_theme_load and sm_theme_save is pure, and tested on
   the host. */

#include "theme_table.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Index of the theme with this id, compared without regard to case; -1 when
   there is none. */
int sm_theme_find(const char *id);
/* Index of the theme a theme file names: its first word. -1 for an empty
   file or a name nobody knows. */
int sm_theme_from_text(const char *text, size_t length);

/* The theme in use, 0 until told otherwise; an index out of range is 0. */
void sm_theme_use(int index);
int sm_theme_current(void);
const char *sm_theme_id(int index);
const char *sm_theme_name(int index);

/* A role's colour in the theme in use: its three bytes, and as libdragon's
   graphics calls take it. */
const unsigned char *sm_colour_rgb(sm_colour_role_t role);
uint32_t sm_colour(sm_colour_role_t role);

/* Read the card's choice and use it. A missing or unreadable file changes
   nothing. Returns whether a theme was chosen by the file. */
bool sm_theme_load(const char *path);
/* Write the theme in use as the card's choice: its id and a newline. */
bool sm_theme_save(const char *path);

#endif
