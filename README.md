# Lyric Chunker

A Blender add-on that automates the syllable-chunk pipeline for the music
visualizer workflow: type a delimited lyric line, get styled 3D text split
into per-syllable chunk objects, then batch-render each chunk as a
transparent 16-bit PNG for compositing in DaVinci Resolve (Fusion).

Works on Blender 4.x and 5.x (tested against the 5.1 API).

## Install

1. Edit > Preferences > Add-ons
2. Click the dropdown arrow (top right) > **Install from Disk…**
   (in Blender 5.x this is the "legacy add-on" path — single `.py` files
   install here, no zip needed)
3. Pick `lyric_chunker.py`, enable **Lyric Chunker**
4. The panel appears in the 3D Viewport sidebar (press `N`) under the
   **Lyric Chunker** tab

## Usage

1. **Style once by hand:** create a text object, set its font, extrude,
   bevel, material, scale, rotation, and position where the line should sit.
   Pick it as the **Template** in the Style section. Every generated line
   inherits all of it. (No template? Defaults are used at the 3D cursor and
   the panel warns you.)
2. **Type the line** with delimiters: `sala-zar has my boots`
   - `-` splits syllables within a word
   - space splits words (whole words are single chunks unless you add `-`)
   - `\-` renders a literal hyphen without splitting
3. **Generate Chunks.** You get objects `Line1_Chunk1` … `Line1_Chunk5` in a
   `Line1` collection, each with its own center-of-mass origin. The line
   number auto-increments for the next line. Re-generating an existing line
   number replaces it.
4. **Set the Output Root** and hit **Render Line N** (or **Render All
   Lines**). Each chunk renders alone — everything else in your Line
   collections is hidden for that frame — and saves to
   `<output root>/Line1/Line1_Chunk1.png` (PNG, RGBA, 16-bit, transparent
   film). Your scene's render output settings are restored afterward.

The **Render Line** button targets, in order: the line of the currently
active object (click any chunk to render its line), otherwise the last line
you generated, otherwise the Line Number field.

## Notes

- **Force Uppercase** (default on) uppercases the text before generating —
  matches the project's visual style and keeps glyph detection robust
  (lowercase i/j dots are separate mesh islands).
- **Zero-pad Numbers** switches naming to `Line01_Chunk01`. Default off to
  match the existing Resolve bins.
- A hidden `_LyricBackups` collection keeps an untouched copy of each line's
  original text object (`Line#_source`) in case you need to re-style or
  regenerate later.
- Chunk detection clusters mesh islands by X overlap, so dotted/accented
  glyphs stay whole. If a font's ligatures merge letters (or a glyph like a
  straight double-quote splits oddly), generation fails with a clear error
  instead of mis-splitting — try a different font or rewording.
- Film > Transparent is enabled automatically at render time if it's off
  (noted in the Status box).
- The template object is hidden from renders automatically during a batch,
  then restored.

## Dev loop

Open `lyric_chunker.py` in Blender's Text Editor and hit Run Script to
re-register after edits (the script unregisters itself first, so re-running
is safe). For headless render tests:

```
blender --background scene.blend --python lyric_chunker.py
```

Pure logic (line parsing, glyph clustering) has no `bpy` dependency and can
be unit-tested outside Blender.

## Releasing

Every push to `main` that changes `lyric_chunker.py` triggers the
`sync-downloads` GitHub Action, which copies the file into the Dabingabongo
repo's `/downloads/` folder and refreshes its `downloads.json` entry
(version from `bl_info`, size, date — plus a changelog entry when the
version changed, using the commit subject as the note). Bump the `bl_info`
version when the change is worth a changelog line. The push to Dabingabongo
`main` kicks off its Netlify deploy, so the live downloads page updates on
its own. The action needs a `LYRIC_CHUNKER_SYNC` repo secret (a
fine-grained PAT with Contents read/write on `mikeyd433/Dabingabongo`).
