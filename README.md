# Lyric Chunker

A Blender add-on that automates the syllable-chunk pipeline for lyric /
music video work: type delimited lyrics, get styled 3D text split into
per-syllable chunk objects, batch-render each chunk as a full-frame
transparent 16-bit PNG, and get a **JSON manifest per line** carrying
every chunk's text, screen position, pixel bbox, and timing — the direct
input for compositing in DaVinci Resolve (Fusion).

The product boundary: **stills out of Blender, plus (soon) a generated
Fusion comp with timing already in place.** Animation and retiming stay
in Fusion. See `docs/lyric_chunker_spec_addendum.md` for the full spec.

Requires Blender **4.2 LTS or newer**.

## v2 breaking changes

This is a ground-up rewrite of the v1 single-file add-on:

- **The delimiter is now `|` (configurable), not `-`.** Hyphens are
  literal characters — `well-worn` renders as-is and never splits. The
  old `\-` escape is gone.
- Chunks are generated as **one Text object per chunk** (positioned by
  prefix measurement) instead of mesh-island clustering. No mesh
  conversion: chunks stay live, editable text, and extrude/bevel live on
  the text data. The old ligature/glyph-count failure mode is gone.
- Renders now write a `Line#.json` manifest next to the PNGs.
- Packaged as a Blender **Extension** (`blender_manifest.toml`); the
  single-file build on the downloads page is generated from it.

## Install

**Extension (recommended):** build the zip
(`python3 scripts/build_single_file.py --zip dist/`) and install via
Edit > Preferences > Get Extensions > Install from Disk.

**Single file (dabingabongo.com/downloads):** Edit > Preferences >
Add-ons > Install from Disk… and pick `lyric_chunker.py` (in Blender
4.2+ this is the legacy add-on path).

The panel appears in the 3D Viewport sidebar (`N`) under **Lyric
Chunker**.

## Usage

1. **Set up the scene.** Either press **Set Up Scene** (creates a
   camera, light, and template text object inside a `LyricChunker`
   collection — never touches existing objects) or point the Template
   and Camera pickers at your own hand-built setup. The generated
   template ships with the project house style: Georgia Bold Italic
   (when the font is found on your machine), extrude 0.12, round bevel
   0.03 @ resolution 4, character spacing 1.1, word spacing 1.4, white
   Principled material. Style the template
   once: font, extrude, bevel, material, scale, rotation, position.
   Every generated chunk inherits all of it.
2. **Type the lyrics.** Type a line into the panel field and press `+`
   (Add Line) — it lands in the line list below, labeled with its real
   number (`Line 17`, `Line 18`, … following Start Index). Rows stay
   editable in place; select a row to target it with the Generate/Render
   Line N buttons. `Some|thing wick|ed this way comes` → chunks `Some /
   thing / wick / ed / this / way / comes`. For pasting a whole song at
   once, attach a text datablock (bottom row of the Lyrics box), edit it
   in the Text Editor, and hit the import button to pull its rows into
   the list.
3. **Generate.** One Text object per chunk lands in a `Line#`
   collection, positioned so the chunks composite back into the full
   line. Chunks are editable text — fix a typo by editing the object's
   body, then **Re-render Chunk**.
4. **Timing (optional).**
   - **SRT import:** pick a subtitle file; entry N supplies line N's
     start/end (content still comes from your delimited text, not the
     SRT). Chunk starts are distributed across the line span, weighted
     by chunk length.
   - **Timeline markers:** load the song in the VSE, scrub, and tap `M`
     along to the vocal. A marker named `Line1_Chunk1` binds to that
     chunk directly (recommended); unnamed markers map to chunks in
     order. **Markers win over SRT per chunk.**
   - **Tap Timing:** the fastest route to real syllable timing. Press
     **Tap Line N** or **Tap All**, the scene starts playing, and each
     tap (Enter or click) drops a marker named for the next chunk in
     order — no hand-naming. Backspace undoes the last tap, Esc
     finishes.
   - **Preview Timing** keyframes each chunk's viewport colour white →
     highlight at its start time, so you can scrub against the song and
     check the timing before going near Resolve. It's viewport-only and
     never affects renders; **Clear Preview** removes it.
   - Timing is a scaffold — chunks get a start time only, and you
     fine-tune in Fusion. No end times: hold-until-line-clears is a
     comp-side decision.
5. **Render.** Set the Output Root and hit **Render Line N** or **Render
   All Lines**. Rendering runs as a cancellable queue with a progress
   readout; each chunk renders alone, full-frame, transparent, 16-bit
   PNG, to `<root>/Line1/Line1_Chunk1.png`, with `Line1.json` alongside.
   Cancelling still writes a partial manifest for completed chunks. Your
   render output settings are restored afterward.
6. **Check the result.** **Contact Sheet** renders everything at low res
   into one preview image before you commit to a full batch. **Verify
   Line** renders the full line as a single text object, composites your
   chunk PNGs, and diffs them — pass/fail lands in the manifest's
   `verification` block (threshold in add-on preferences).

## The manifest

One JSON file per line (`manifest_version: 1`), consumed by the future
Fusion comp generator and safe to build on. Highlights:

- `start_seconds` is canonical timing; `start_frame` is derived
  convenience.
- `bbox_px` is `[x_min, y_min, x_max, y_max]` in pixels with **origin at
  bottom-left** (matches Blender's camera view and Fusion — most image
  libraries are top-left, so flip accordingly).
- `manual_offset_x` records your viewport nudges separately from the
  computed offset, so regeneration doesn't clobber corrections.
- `song.json` at the output root is reserved — don't put anything there.

## Known limitations

- **Cross-boundary kerning:** the offset measurement captures the
  kerning pair straddling a chunk boundary, but the glyphs live in
  separate objects, so aggressive kerning tables on display faces can
  still drift visibly. Use **Verify Line** to check your exact font, and
  nudge chunks manually if needed (recorded as `manual_offset_x`).
- **No non-Latin script support:** splitting assumes whitespace word
  separation, which does not hold for CJK.
- No animation or keyframing inside Blender — timing lives in Fusion.
- No automatic syllable detection from audio — input is hand-delimited.

## Dev loop

The canonical source is the `lyric_chunker/` package. For quick
iteration, build the flat file and run it from Blender's Text Editor
(it unregisters itself first, so re-running is safe):

```
python3 scripts/build_single_file.py --out build/lyric_chunker.py
```

Pure logic (splitting, SRT parsing, timing distribution, manifest,
marker matching) has no `bpy` dependency:

```
python3 -m pytest tests/
```

## Releasing

Every push to `main` that changes `lyric_chunker/` triggers the
`sync-downloads` GitHub Action: it runs the tests, builds the
single-file add-on, and copies it into the Dabingabongo repo's
`/downloads/` folder, refreshing its `downloads.json` entry (version
from the generated `bl_info`, which mirrors `blender_manifest.toml` —
the build fails if they disagree). Bump the version in **both**
`lyric_chunker/blender_manifest.toml` and `ADDON_VERSION` in
`lyric_chunker/manifest.py` when the change is worth a changelog line.
The push to Dabingabongo `main` kicks off its Netlify deploy. The action
needs a `LYRIC_CHUNKER_SYNC` repo secret (a fine-grained PAT with
Contents read/write on `mikeyd433/Dabingabongo`).

The Superhive product ships as an Extension zip:
`python3 scripts/build_single_file.py --zip dist/`.

## Fusion comp generation (experimental)

`scripts/generate_comp.py` turns each `Line#.json` manifest into a
pasteable Fusion node graph (`Line#.setting`) replicating the reference
lyric-video look: per chunk, `Loader → ColorGain → Transform` merged in
order, with a one-frame white→orange flip (Gain G/B 1.0→0.4/0.05) and a
PolyPath bounce (Center Y dips 0.015, frames S/S+1/S+4) keyed at each
chunk's manifest start frame, in line-local time.

```
python3 scripts/generate_comp.py <output_root>            # all lines
python3 scripts/generate_comp.py Line16/Line16.json --clip-dir "C:\path\Line 16"
```

Open the `.setting` in a text editor, copy all, click an empty spot in
the Fusion node area, paste, and wire the last Merge to MediaOut.
Highlight color and bounce are tunable via `--highlight`, `--dip-depth`,
`--dip-in`, `--dip-out`.

Generated graphs use Loader nodes (Media Pool IDs can't be fabricated
from outside Resolve), verified working on Resolve 21's Fusion page.
Because Fusion resolves the numbered chunk PNGs into one image
sequence, each Loader trims to its own frame of that sequence.

### Skipping the paste — Resolve script (experimental)

`resolve/LyricChunker_BuildComp.py` does the paste for you: install it
into Resolve's Fusion `Scripts/Comp` folder (path in the file header),
open the Fusion page on a Fusion Composition clip, and run
**Workspace > Scripts > Comp > LyricChunker_BuildComp**. Give it the
output root and a line number and it pastes that line's graph and wires
it to MediaOut. It pastes the same `.setting` text that works by hand,
so if a scripting call misbehaves it says so in the console and the
manual paste still works.
