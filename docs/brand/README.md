# Brand — the badger mark

<p align="center">
  <img src="logo.svg" width="160" alt="ai-badger">
</p>

[`logo.svg`](logo.svg) is the ai-badger mark: a badger whose facial stripes are circuit traces,
peeking over a terminal window with its paws on the edge.

It is hand-authored SVG. Nothing was traced from a photograph, so no third-party licence attaches
to it and the project can use it anywhere without attribution.

## What it is saying

The two halves of the name, in one picture. The **badger** is the animal the project is named for,
drawn as a character rather than a silhouette — it looks back at you. The **circuit traces** run
down the stripes rather than sitting beside the animal as a bolted-on gadget, so the technology
idea survives the mark being scaled down or redrawn later. The **terminal** is where the project
actually lives, and the paws over its edge are the README's own line — the badger digs the
framework into your repo — drawn instead of asserted.

Three earlier propositions (a bare circuit badger, an amber terminal mascot, and a flat 16 px
glyph) were considered and dropped in favour of this one; they are in the history of
[PR #125](https://github.com/Arasz/ai-badger/pull/125) if a variant ever needs to start from one
of them.

## Specification

| | |
|---|---|
| **Canvas** | 256×256, rounded-square field, `rx="56"` |
| **Accent** | `#2BD9C0` teal — traces, eyes, prompt, hairlines |
| **Field** | `#16202C` → `#0A1017` vertical gradient |
| **Fur** | `#FFFFFF` → `#D7E0EA` vertical gradient |
| **Ink** | `#161C24` stripes, `#0A1017` outlines |
| **Terminal** | `#111823` body, `#1C2634` title bar |
| **Best at** | 96 px and up |

## Using the mark

The README hero is a single line in [`README.md`](../../README.md):

```html
<img src="docs/brand/logo.svg" width="128" alt="ai-badger">
```

**Clear space** — leave at least 1/8 of the mark's width empty on every side. The rounded-square
field is part of the mark; do not crop to the head, and do not place the mark on a busy
background.

**Do not** recolour the accent per context, stretch the square, add a drop shadow, or set the
badger over a photograph. If a variant is needed that this file does not cover, add it to this
directory rather than editing a copy at the call site.

## Not yet drawn

None of these blocks using the mark; each is worth doing when something actually needs it.

- **A wordmark lockup** — mark plus "ai-badger" set horizontally, for a social card. The
  letterforms must be converted to outlines rather than left as SVG `<text>`; `<text>` renders
  with whatever font the viewer happens to have, which is not the same picture twice.
- **A monochrome variant** — one flat colour, for places that will not take a full-colour mark.
- **A small-size variant** — this mark carries too much detail below ~96 px. A favicon and a
  plugin icon need the head alone, simplified, without the terminal.
- **Raster exports** — PNG at 16/32/180/512 px, since GitHub social previews and OS app icons do
  not accept SVG.

## Editing

To preview a change on macOS without opening a design tool:

```bash
qlmanage -t -s 420 -o /tmp docs/brand/logo.svg
```

Check any edit at 16 px too — that is where geometry mistakes become visible.
