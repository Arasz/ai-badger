# Brand — the badger mark

Three logo propositions for ai-badger. **None of them is final** — pick one (or one to develop
further), and the rest of this document explains what changes once you do.

All three are hand-authored SVG. Nothing was traced from a photograph, so there is no third-party
licence attached to any of them and the repository can use them anywhere without attribution.

## The three propositions

| | A — Circuit Badger | B — Terminal Badger | C — Glyph Badger |
|---|---|---|---|
| | <img src="proposal-a-circuit-badger.svg" width="120" alt="Circuit Badger"> | <img src="proposal-b-terminal-badger.svg" width="120" alt="Terminal Badger"> | <img src="proposal-c-glyph-badger.svg" width="120" alt="Glyph Badger"> |
| **Idea** | The badger's facial stripes *are* circuit traces — the animal and the technology are the same mark, not an animal wearing a gadget. | The badger peeks over a terminal window with its paws on the edge. It is the "digs into your repo" line from the README, drawn. | The head reduced to flat geometry, with a three-node neural chain running down the blaze. |
| **Feels like** | Product logo | Mascot / character | System icon |
| **Accent** | `#2BD9C0` teal | `#FFB454` amber | `#5A6BFF` indigo |
| **Field** | Dark slate | Near-black | Light |
| **Best at** | 64 px and up | 96 px and up | 16 px and up |
| **Weakest at** | Traces mush together below ~48 px | Too much detail for a favicon | Least distinctive of the three |

### A — Circuit Badger

The recommendation, and what the README currently uses. It is the only one of the three where the
AI/technology idea is carried by the badger itself rather than by something placed next to it,
which is what makes it survive being scaled down and being redrawn later. Teal on slate keeps it
legible on both a light and a dark README.

### B — Terminal Badger

The most charming and the most limited. A peeking mascot needs room — at small sizes the paws,
the prompt, and the face collapse into noise. Best understood as a companion illustration (docs
header, social card, the top of the getting-started guide) rather than the primary mark. If you
want a *character* for the project rather than a *logo*, this is the one to develop.

### C — Glyph Badger

The safe, boring, useful one. Flat fills, no gradients, four colours; it is the only proposition
that still reads as a badger at 16 px, which is what a plugin icon and a favicon need. Reasonable
as the app-icon companion to whichever of A or B becomes the brand mark.

## Once a direction is picked

These are deliberately *not* done yet, because doing them before the choice wastes the work:

- **A wordmark lockup** — mark plus "ai-badger" set horizontally, for the README header and social
  card. The letterforms must be converted to outlines rather than left as SVG `<text>`; `<text>`
  renders with whatever font the viewer happens to have, which is not the same picture twice.
- **A monochrome variant** — one flat colour, for places that will not take a full-colour mark.
- **Raster exports** — PNG at 16/32/180/512 px, since GitHub social previews and OS app icons do
  not accept SVG.
- **Deleting the other two** from this directory.

## Using the mark

The README hero is a single line in [`README.md`](../../README.md):

```html
<img src="docs/brand/proposal-a-circuit-badger.svg" width="128" alt="ai-badger">
```

Swapping propositions means changing that filename and nothing else.

**Clear space** — leave at least 1/8 of the mark's width empty on every side. The rounded-square
field is part of the mark; do not crop to the head or place the mark on a busy background.

**Do not** recolour the accent per context, stretch the square, add a drop shadow, or set the
badger over a photograph. If a variant is needed that these files do not cover, add it here rather
than editing a copy at the call site.

## Editing

Every file is plain SVG on a 256×256 viewBox with a rounded-square field (`rx="56"`), so the three
are directly comparable and interchangeable. To preview a change on macOS without opening a design
tool:

```bash
qlmanage -t -s 420 -o /tmp docs/brand/proposal-a-circuit-badger.svg
```

Check any edit at 16 px too — that is where geometry mistakes become visible.
