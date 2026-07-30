# Lyric Chunker — Spec Addendum v2

**Read alongside `lyric_chunker_spec.md`.** This document does not replace that
spec. It records decisions made after it was written, and where the two
conflict, **this document wins**.

Scope has changed since the original spec. The add-on is now being built as a
product for sale on Superhive, positioned narrowly as a **lyric/music video
tool for Blender + DaVinci Resolve users**, widening only in v2. Several things
the original spec deferred are no longer deferrable, and several internal
formats are now public contracts.

The product boundary is now: **stills out of Blender, plus a generated Fusion
comp with timing already in place.** Animation and retiming stay in Fusion.

---

## 0. Settled decisions

| ID | Decision | Resolution |
|----|----------|-----------|
| D1 | Syllable delimiter | **Configurable field, `\|` default** |
| D2 | Unsplit words become single chunks | **Yes** (rules in §9) |
| D3 | Text placement | **Template object location** |
| D4 | Multi-line batch input | **In scope for v1** (was deferred) |
| D5 | Camera per line | **Single fixed camera**, unchanged |
| A1 | Chunk generation method | **Per-chunk Text objects** (replaces loose-parts split) |
| A2 | Output framing | **Full-frame**, pixel bbox recorded in manifest |
| A3 | Sidecar data file | **Yes — JSON manifest per line**, schema in §1 |
| A4 | Render loop structure | **Modal operator over a job queue** |
| A5 | Packaging | **Blender Extension (`blender_manifest.toml`)**, 4.2 LTS floor |
| A6 | Scene setup | **Optional "Set Up Scene" button**, non-destructive (§5.0) |
| A7 | Output scope | **Stills + generated Fusion comp.** No animation in Blender |
| A8 | Buyer scope | **Lyric/music video first**, general kinetic typography deferred to v2 |
| A9 | Timing source | **Both SRT import and Blender timeline markers** (§4) |
| A10 | Chunk distribution | **Weighted by chunk character length** (§4.4) |
| A11 | Comp target | **UNRESOLVED — blocking research task, see §7** |

---

## 1. NEW — JSON manifest

### 1.1 Why

At generation time the add-on knows each chunk's source text, world position,
camera-space position, pixel extents, and now its timing. Saving a PNG destroys
all of it. A file named `Line1_Chunk3.png` preserves ordering and nothing else.

This is a one-way door. Recovering screen positions after the fact requires
regenerating the geometry, so any line rendered before the manifest exists is
permanently missing its data.

It is also the direct input to the comp generator (§6). Without it, there is no
product.

### 1.2 Location

One manifest per line, written into that line's output folder:

```
<output_root>/
  Line1/
    Line1_Chunk1.png
    Line1_Chunk2.png
    Line1.json
  Line2/
    ...
```

### 1.3 Schema

```json
{
  "manifest_version": 1,
  "generator": {
    "addon": "lyric_chunker",
    "addon_version": "1.0.0",
    "blender_version": "4.2.1"
  },
  "project": {
    "blend_file": "song_visuals.blend",
    "scene": "Scene",
    "camera": "Camera",
    "style_preset": "MainTitle",
    "template_object": "STYLE_Template"
  },
  "render": {
    "engine": "BLENDER_EEVEE_NEXT",
    "resolution_x": 1920,
    "resolution_y": 1080,
    "resolution_percentage": 100,
    "fps": 24,
    "fps_base": 1.0,
    "film_transparent": true,
    "color_depth": "16",
    "file_format": "PNG"
  },
  "line": {
    "index": 1,
    "text_raw": "Some|thing wick|ed this way comes",
    "delimiter": "|",
    "output_dir": "Line1",
    "start_seconds": 12.5,
    "end_seconds": 15.0,
    "timing_source": "srt"
  },
  "chunks": [
    {
      "index": 1,
      "name": "Line1_Chunk1",
      "text": "Some",
      "filename": "Line1_Chunk1.png",
      "world_position": [0.0, 0.0, 0.0],
      "screen_position": [0.312, 0.500],
      "bbox_px": [412, 476, 588, 604],
      "offset_x": 0.0,
      "manual_offset_x": 0.0,
      "start_seconds": 12.5,
      "start_frame": 300,
      "timing_source": "srt"
    }
  ],
  "verification": {
    "run": true,
    "max_pixel_delta": 2,
    "passed": true
  },
  "rendered_at": "2026-07-29T14:02:11Z"
}
```

### 1.4 Field notes

- **`manifest_version`** — integer, increments on breaking schema change.
  Present from v1 because buyers will build on this format. Never reuse a
  version number for a changed shape.
- **`screen_position`** — normalized camera-space position of the chunk origin,
  from `bpy_extras.object_utils.world_to_camera_view(scene, camera, obj.matrix_world.translation)`.
  That function exists for exactly this purpose; don't hand-roll the projection.
- **`bbox_px`** — `[x_min, y_min, x_max, y_max]`, pixel coordinates,
  **origin at bottom-left**. Matches both Blender's camera-view convention and
  Fusion's normalized coordinate origin. Most image libraries use top-left, so
  state this in user-facing docs or every downstream integration will be
  flipped vertically.
- **`offset_x`** — computed cumulative-prefix offset (§2.3).
- **`manual_offset_x`** — user nudge from the UI, default `0.0`. Kept separate
  so regeneration doesn't clobber manual corrections.
- **`start_seconds`** — **canonical timing value.** Seconds, not frames, so the
  data survives a frame rate change.
- **`start_frame`** — derived from `start_seconds` × `fps`. Convenience only;
  never the source of truth.
- **`timing_source`** — `"srt"`, `"marker"`, or `"none"`. Recorded per chunk as
  well as per line, because markers may cover some chunks and not others.
- **No end times per chunk.** Chunk visibility duration is a comp-side
  decision, not a Blender one. See §4.5.

### 1.5 Cross-line index (v1.5, reserve the filename)

A `song.json` at `<output_root>` aggregating all lines. Not in v1. Do not use
that filename for anything else.

---

## 2. CHANGED — chunk generation architecture

### 2.1 What's being replaced

The original spec generates one Text object for the whole line, converts to
mesh, separates by loose parts, and regroups islands into chunks.

**This does not work reliably.** Islands do not correspond to characters, and it
fails in both directions:

- **More islands than characters:** `i`, `j`, `?`, `!`, `%`, `=`, `"`, `:`, `;`,
  and every accented vowel (`é`, `ü`, `ñ`) are multiple disconnected pieces.
- **Fewer islands than characters:** bevel or extrude can fuse adjacent glyphs
  into one island. Script and blackletter faces do it by design.

Regrouping therefore requires a heuristic — typically sorting islands by X and
looking for gaps — which degrades under tight kerning and fails outright on
overlapping italics. It will pass a test line and break on line 23 of a real
song.

### 2.2 Replacement

**Generate one Text object per chunk**, from the chunk substring, positioned by
cumulative-prefix measurement.

Additional benefits:

- Text objects support extrude and bevel natively, so **mesh conversion may not
  be needed at all**. Verify against the intended style; if the look is
  achievable on the Text object directly, drop `bpy.ops.object.convert` from the
  pipeline entirely.
- Each chunk stays live editable text, making single-chunk re-render (§5.1)
  trivial — fix a typo by editing a string, not regenerating a line.
- No `bmesh` island analysis, no `bpy.ops.mesh.separate` context juggling. Both
  were flagged as footguns in the original build notes; both are now moot.

### 2.3 Offset computation

For chunks `["Some", "thing", "wick", "ed"]`:

1. Create a temporary Text object using the template object's font and style
   settings.
2. For each chunk boundary, set the temp object's `body` to the cumulative
   prefix (`"Some"`, then `"Something"`, then `"Somethingwick"`, …).
3. Read the evaluated width. Use the depsgraph-evaluated object, not the raw
   datablock — text dimensions are not valid until evaluation:
   ```python
   deps = context.evaluated_depsgraph_get()
   eval_obj = temp.evaluated_get(deps)
   width = eval_obj.dimensions.x
   ```
4. Chunk `i`'s `offset_x` is the width of the prefix ending just before it.
5. Delete the temp object.

Apply the same horizontal alignment setting as the template object throughout,
or offsets will be measured against a different origin than they're applied to.

### 2.4 Known limitation — cross-boundary kerning

Kerning within each prefix is correct. The pair straddling a chunk boundary is
not applied, because the two glyphs now live in different objects.

Magnitude: usually sub-pixel. Visible on display faces with aggressive kerning
tables. Mitigated by `manual_offset_x`, detected by §2.5.

**State this limitation in the product documentation.** It is a support ticket
otherwise.

### 2.5 NEW — "Verify Line" button

1. Render the full line as a single Text object to a temp buffer.
2. Render all chunks and composite them.
3. Diff. Report max per-pixel delta and pass/fail against a threshold.

Write the result into `verification` in the manifest. Default threshold: 2.
Expose in preferences.

Roughly forty lines of code, and it is the difference between "kerning is
probably fine" and "kerning is fine for this font."

---

## 3. CHANGED — render architecture

### 3.1 Modal job queue

40 lines × 4 chunks = 160 renders. A synchronous loop freezes Blender's UI with
no progress and no cancel; users will force-quit and lose the batch.

Structure the render step as a **modal operator consuming a job queue**, with a
timer, even when the queue holds a single item. Requirements:

- Progress readout: `Rendering Line 7, chunk 2 of 4 — 31/160`
- Cancel button that stops cleanly after the in-flight render
- On cancel or error, write a partial manifest with the chunks that did complete
- Never block on `bpy.ops.render.render()` inside a loop

This is the actual cost of multi-line support. The iteration is trivial; the
progress and cancel UX is not.

### 3.2 Isolate the render strategy

```python
def render_chunks(chunks, settings) -> list[Path]:
    ...
```

Do not inline per-chunk rendering into the operator. See §6.4.

### 3.3 Assert render settings

Before any batch, assert and warn on mismatch:

- `scene.render.film_transparent = True`
- `image_settings.file_format = 'PNG'`
- `image_settings.color_mode = 'RGBA'`
- `image_settings.color_depth = '16'`

Silently losing `film_transparent` ruins an entire batch invisibly. Check every
run; do not assume it survived since last session.

---

## 4. NEW — timing

### 4.1 The core constraint

**No importable format carries chunk-level timing.** SRT and plain LRC are
line-level. Enhanced LRC is word-level at best, and rare. Syllable-level
timestamps effectively do not exist as a distributable file format.

Therefore: **import produces a scaffold, not final timing.** The user fine-tunes
in Fusion. Design accordingly — do not build elaborate timing machinery in
Blender to produce something the user will adjust anyway.

### 4.2 Source 1 — SRT import

SRT is the primary import target over LRC because it carries start *and* end
times (so line span is known rather than guessed), it parses in ~30 lines, and
buyers can produce one from any subtitle tool.

- File picker in the panel, parsed on load
- Subtitle entries map to lines **in order**; entry N supplies line N's
  `start_seconds` and `end_seconds`
- SRT text is **not** used as the lyric text — the user's delimited text block
  remains the source of truth for content, because SRT won't contain the `|`
  delimiters
- Warn on count mismatch between SRT entries and text block lines; do not fail
- Support the start-index offset from §5.3, so lines 12–20 map to SRT entries
  12–20

*Unverified:* Resolve can transcribe audio to subtitles directly, but that
feature may be Studio-only. Confirm before referencing it in marketing or docs.

### 4.3 Source 2 — Blender timeline markers

The only route to genuine chunk-level timing without building new UI. The user
loads the song into the VSE, scrubs with audio, and taps `M` along to the vocal.

Matching rules, in priority order:

1. **Named markers** — a marker named `Line1_Chunk1` binds to that chunk
   directly. Robust against stray markers and reordering. Recommend this in docs.
2. **Positional fallback** — if no named markers are found, map markers to
   chunks in chronological order.
3. **Count mismatch** — warn with specifics (`14 markers, 17 chunks`), apply
   what matches, leave the rest at `timing_source: "none"`.

### 4.4 Precedence and distribution

When both sources are present, **markers win per chunk.** Markers are manually
placed and chunk-level; SRT-derived timing is interpolated. A chunk with a
marker takes it; chunks without fall back to SRT distribution within their line.

Distribution algorithm (weighted by chunk length):

```
weights   = [max(len(chunk.text), MIN_WEIGHT) for chunk in line.chunks]
total     = sum(weights)
span      = line.end_seconds - line.start_seconds
cursor    = line.start_seconds
for chunk, w in zip(line.chunks, weights):
    chunk.start_seconds = cursor
    cursor += span * (w / total)
```

`MIN_WEIGHT` default `2`. Without a floor, chunks like `"a"` or `"ed"` collapse
to near-zero duration and land visually on top of their neighbour.

Known imprecision worth documenting: character count is a proxy for sung
duration, not a measure of it. `"strength"` is eight characters and one
syllable; `"away"` is four and two. The result is a scaffold, which is all it
claims to be.

### 4.5 What timing does NOT include

Chunks get a **start time only.** No end time, no duration.

Rationale: the standard lyric-video behaviour is that a chunk appears and holds
until the line clears, and that hold is a comp-side property. Baking durations
into the manifest would force a regenerate on every retime, which is exactly
the cost this whole architecture exists to avoid.

The comp generator sets hold-to-end-of-line as its default (§6.2).

---

## 5. NEW — product-track features

### 5.0 "Set Up Scene" button

The original spec assumed an existing scene containing camera, lighting, and a
template object. That holds for the author and fails for every buyer, who
installs the add-on, opens a fresh file, and finds a panel that does nothing.

Add an optional **Set Up Scene** button that creates:

- A camera, framed for a single line of text at the scene's resolution
- A minimal light or world setup sufficient for a flat, tintable render
- A template Text object with sensible default style

Hard requirements — this must be **non-destructive**:

- Never overwrite or modify existing objects
- Create everything inside a dedicated `LyricChunker` collection
- If a camera already exists, warn and offer to use it instead of creating one
- Every created object gets a recognisable name prefix
- Button is never required — the panel must work fully in a hand-built scene

Offer object pickers alongside, so a user with an existing setup points the
add-on at their own camera and template rather than accepting generated ones.

### 5.1 Single-chunk re-render

Re-render one chunk without regenerating the line. Reads the line manifest,
rebuilds only the target chunk from its stored text and offset, overwrites that
PNG, updates the manifest entry and `rendered_at`.

Near-free given §2.2 and §1. The most obviously-missing feature to a buyer who
finds a typo in chunk 3 of 40.

### 5.2 Style presets

Save and load named style configurations (font, size, extrude, bevel, material,
alignment) on the scene. Record the active preset in `project.style_preset`.

### 5.3 Multi-line input

Multi-line text block, one lyric line per row. Line numbers auto-assigned by row
order, with a start-index field so a user can render lines 12–20 without
renumbering. Per-line output folders and manifests as in single-line mode.

### 5.4 Contact sheet preview

Low-resolution pass over all chunks composited into one image, shown before
committing to a full batch. Catches bad splits and kerning drift before spending
render time.

### 5.5 Error surface

No console-only failures. Every failure path needs a panel-visible message:
missing template object, unwritable output path, empty line text, delimiter
producing zero-length chunks, camera missing, font file unresolved, SRT parse
failure, marker count mismatch.

---

## 6. Fusion comp generation

**Promoted from v2 to core roadmap.** This is the feature that turns a folder of
PNGs into a product. Without it the add-on does the tedious half of the job and
hands the buyer a folder; with it, the demo is "type lyrics, import timing, open
a finished comp."

### 6.1 Principle

`.comp` files are plain text and can be written programmatically. The manifest
(§1) is the complete input — nothing else is needed.

### 6.2 What the generated comp contains

- One media node per chunk, pointing at its PNG
- Chunks positioned at frame `start_frame` from the manifest
- Default visibility: appear at start, hold until end of line
- Merge chain assembling chunks in order
- Resolution and frame rate matched to `render` block values
- Nodes named to match chunk names, so the graph is navigable

Because output is full-frame (§4 below), no Transform nodes are needed — chunks
stack at origin and land correctly.

### 6.3 Delivery mechanism — two candidates

1. **Write a `.comp` file to disk** for the user to open.
2. **Put comp text on the clipboard** for the user to paste into the node graph.
   Fusion accepts pasted node graphs as text, and this may prove more portable
   across hosts than file loading.

Evaluate both during §7 research. Clipboard may turn out to be the more reliable
path.

### 6.4 Deferred — single-pass render via Object Index (v1.5)

Currently N chunks means N full renders, each paying scene setup and sampling.
Instead: assign each chunk an Object Index, use ID Mask nodes feeding per-chunk
File Output nodes, and one render produces every chunk PNG.

Chunks in a line never overlap, so masking the beauty pass yields correct
per-chunk RGBA with no occlusion issues. Modest gain under EEVEE, very large
under Cycles.

**Hook:** §3.2. Swapping strategies must be a one-function change.

### 6.5 Deferred — forced alignment (v2, external only)

whisperX / aeneas / MFA can generate word or phoneme timings from audio plus
text. Best quality available.

**Never bundle it.** Multi-hundred-MB model downloads and platform-specific
installs inside a paid Blender add-on is an unmanageable support burden. If it
happens, ship it as a separate script that emits JSON the add-on imports.

---

## 7. BLOCKING RESEARCH — comp target

**Do this before writing any comp generator code.** Resolve's Fusion page and
standalone Fusion Studio handle media differently — the page normally sources
media via `MediaIn`/`MediaOut` from the timeline, while Fusion Studio uses
`Loader`/`Saver` nodes reading from disk. A comp generated for one may not open
correctly in the other, and getting this wrong invalidates the generator's core
assumption.

Verify directly rather than trusting documentation:

1. In Resolve's Fusion page, build a small comp that loads two PNGs from disk.
   Save it. **Read the resulting `.comp` in a text editor** and note which node
   types appear.
2. Do the same in Fusion Studio if available. Diff the two files.
3. Test whether Resolve's Fusion page will open a `.comp` file written by hand.
4. Test whether pasting comp text into the Fusion page node graph works (§6.3).
5. Check how frame rate and timeline start frame are represented, and whether a
   generated comp needs to know the Resolve timeline's start timecode.
6. Determine whether `Loader` nodes function in Resolve's Fusion page at all.

Output of this task: a decision on A11, and a short reference note on the `.comp`
format written into the Fountain of Knowledge.

If it turns out only one host is practical, that's fine — it narrows the product
claim, and narrow was the chosen strategy. It just needs to be stated accurately
on the store page.

---

## 8. Output framing

**Full-frame output.** Each PNG is full render resolution with the chunk in its
final position, transparent elsewhere.

Every chunk drops into Fusion at origin and stacks correctly with no positioning
work — that is the manual labor the tool exists to remove, and it's what lets the
comp generator skip Transform nodes entirely. PNG compresses uniform alpha
extremely well, so the penalty is a few hundred KB per frame.

Cropping is not foreclosed. Because `bbox_px` is recorded, cropping becomes a
lossless post-step with a recoverable offset. Ship an optional "crop on export"
checkbox if buyers ask; do not build for it in v1.

---

## 9. Splitting rules (resolves D1 + D2)

Delimiter is a UI text field, default `|`.

1. Split the line on whitespace into words.
2. Split each word on the delimiter into chunks.
3. Whitespace is always a chunk boundary; the delimiter creates sub-word splits.
4. Discard zero-length chunks; warn if any were produced (usually a doubled
   delimiter typo).

`"Some|thing wick|ed this way comes"` → `["Some", "thing", "wick", "ed", "this", "way", "comes"]`

Rejected: hyphen as default. It collides with real hyphens (`well-worn`) and
em-dashes in lyrics. `|` never appears in sung text.

Not supported in v1: joining two words into one chunk. If it comes up, add a
non-splitting space marker rather than requiring explicit delimiters everywhere.

---

## 10. Packaging and platform

### 10.1 Extension format

Package as a **Blender Extension** with `blender_manifest.toml`, not legacy
`bl_info`.

### 10.2 Version floor

**Blender 4.2 LTS.** LTS gives a long support window against a marketplace
policy that ties purchases to a defined support period, and avoids chasing API
churn across every 4.x release. Test against latest stable too; don't raise the
floor without a concrete reason.

Budget honestly for maintenance — Blender's API breaks between releases and a
paid add-on carries an ongoing obligation.

### 10.3 Multi-file structure

```
lyric_chunker/
  blender_manifest.toml
  __init__.py          # registration only
  properties.py        # PropertyGroup / scene state
  ui.py                # panel
  ops_setup.py         # Set Up Scene
  ops_generate.py      # chunk generation
  ops_render.py        # modal render queue
  ops_verify.py        # verify line
  timing_srt.py        # SRT parse + distribution
  timing_markers.py    # marker matching
  manifest.py          # JSON read/write, schema version
  measure.py           # prefix width measurement
  presets.py           # style presets
  comp/                # Fusion comp generation
```

Keep the `unregister` guard from the original build notes — double-registration
on reload is still the most common dev-loop error.

---

## 11. Revised non-goals for v1

Unchanged from the original spec:

- No animation or keyframing inside Blender — timing lives in Fusion
- No per-chunk material variation — neutral tintable material by design
- No automatic syllable detection from audio — input is hand-delimited
- No EXR pipeline — 16-bit PNG is sufficient

**Removed from non-goals** (now in scope): multi-line batch input.

**Newly explicit non-goals:**

- No general-purpose kinetic typography — lyric-shaped input only until v2
- No non-Latin script support in v1. §9 assumes whitespace word separation,
  which does not hold for CJK. Say so in the store listing rather than
  discovering it through refund requests
- No After Effects output

---

## 12. Build order

1. Properties, panel skeleton, Set Up Scene, style presets, error surface
2. **Prefix measurement (§2.3)** — test standalone against `i`, `j`, `é`, `%`,
   and a heavily-kerned display font before building anything on it
3. Chunk generation via per-chunk Text objects
4. Manifest write (§1)
5. Modal render queue (§3.1), single line
6. Verify Line (§2.5)
7. Multi-line input, single-chunk re-render, contact sheet
8. SRT import + weighted distribution (§4.2, §4.4)
9. Marker timing (§4.3)
10. Comp generation (§6) — **gated on §7 research**

Step 2 is load-bearing: if prefix measurement is unreliable, the whole
architecture in §2 needs revisiting. Step 7 research can run in parallel with
steps 1–9 and should start early, since its outcome shapes step 10 entirely.

---

## 13. Still open

- **Zero-padding** (`Line01_Chunk01` vs `Line1_Chunk1`). At product scope,
  padded is probably the better default — new buyers have no existing
  convention and padding sorts correctly in file browsers. Existing projects are
  the only argument for unpadded.
- **Render engine target.** EEVEE Next vs Cycles vs both. Affects the payoff of
  §6.4 and the size of the test matrix.
- **Product name.** "Lyric Chunker" is a good working name and a weak store
  name. Revisit before launch, not before building.
- **Price point and bundle scope** — standalone, or first component of the
  larger music-video toolkit.
- **Superhive support-period policy** — opt in or out, and what that implies for
  paid-upgrade cadence.
