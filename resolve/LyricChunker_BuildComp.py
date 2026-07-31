"""Lyric Chunker — Build Comp (DaVinci Resolve / Fusion script).

Automates the paste step: reads a line's generated .setting file, pastes
its node graph into the current Fusion composition, and wires the last
Merge to MediaOut. Replaces "open in Notepad, Ctrl+A, Ctrl+C, click,
Ctrl+V, drag a wire" with one menu click.

EXPERIMENTAL — the node graph it pastes is the same text that has been
verified by hand in Resolve 21, but Resolve's scripting entry points
(AskUser dialogs, readfile, Paste) have not been exercised on this
install yet. If a step fails, the printed console message says which,
and the manual paste still works exactly as before.

INSTALL
    Copy this file into Resolve's Comp scripts folder:
      Windows  %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\
               Fusion\\Scripts\\Comp\\
      macOS    ~/Library/Application Support/Blackmagic Design/
               DaVinci Resolve/Fusion/Scripts/Comp/
      Linux    ~/.local/share/DaVinciResolve/Fusion/Scripts/Comp/

USE
    1. Put a Fusion Composition on the timeline for the line and open
       the Fusion page on it.
    2. Workspace > Scripts > Comp > LyricChunker_BuildComp
    3. Give it the render output root and the line number.

    Set OUTPUT_ROOT below to skip being asked every time.
"""

import os
import re

# Optional: hard-code your render output root (the folder holding
# Line17/, Line18/, ...) to skip the dialog. Example:
#     OUTPUT_ROOT = r"C:\\Users\\me\\Desktop\\SalazarVisualizar\\Lyrics"
OUTPUT_ROOT = ""

SETTING_RE = re.compile(r"^Line0*(\d+)\.setting$", re.IGNORECASE)


def get_comp():
    """The composition to build into, however the script was launched."""
    comp_obj = globals().get("comp")
    if comp_obj is not None:
        return comp_obj
    fusion_obj = globals().get("fusion")
    if fusion_obj is None:
        try:
            import BlackmagicFusion as bmd
            fusion_obj = bmd.scriptapp("Fusion")
        except Exception:
            return None
    return fusion_obj.GetCurrentComp() if fusion_obj else None


def read_setting_table(path):
    """Load a .setting file into the table structure Paste() expects."""
    try:
        import BlackmagicFusion as bmd
    except ImportError:
        bmd = globals().get("bmd")
    if bmd is None:
        raise RuntimeError(
            "BlackmagicFusion module unavailable — run this from Resolve's "
            "Scripts menu, or paste the .setting by hand"
        )
    table = bmd.readfile(path)
    if not table:
        raise RuntimeError(f"could not read {path}")
    return table


def find_settings(root):
    """{line_no: path} for every Line#.setting under the output root."""
    found = {}
    if not root or not os.path.isdir(root):
        return found
    for entry in sorted(os.listdir(root)):
        folder = os.path.join(root, entry)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            match = SETTING_RE.match(name)
            if match:
                found[int(match.group(1))] = os.path.join(folder, name)
    return found


def ask_for_input(comp, default_root):
    """Dialog for output root + line number. Returns (root, line) or None."""
    try:
        answer = comp.AskUser("Lyric Chunker — Build Comp", {
            1: {
                1: "root", 2: "PathBrowse",
                "Name": "Render output root", "Default": default_root,
            },
            2: {
                1: "line", 2: "Text",
                "Name": "Line number", "Default": "",
            },
        })
    except Exception as exc:
        print("[Lyric Chunker] dialog unavailable (%s) — set OUTPUT_ROOT "
              "at the top of the script instead" % exc)
        return None
    if not answer:
        return None
    return str(answer.get("root", "")).strip(), str(answer.get("line", "")).strip()


def output_tool_for_line(comp, line_no):
    """The end of the pasted chain: the highest-numbered Merge for this
    line, or its single Transform when the line has one chunk."""
    merge_prefix = "Merge_Line%d_" % line_no
    best, best_index = None, -1
    for tool in (comp.GetToolList(False, "Merge") or {}).values():
        name = tool.Name
        if not name.startswith(merge_prefix):
            continue
        digits = ""
        for char in name[len(merge_prefix):]:
            if not char.isdigit():
                break
            digits += char
        if digits and int(digits) > best_index:
            best, best_index = tool, int(digits)
    if best is not None:
        return best
    move_prefix = "Move_Line%d_" % line_no
    for tool in (comp.GetToolList(False, "Transform") or {}).values():
        if tool.Name.startswith(move_prefix):
            return tool
    return None


def connect_to_media_out(comp, source):
    """Wire the chain end into MediaOut. Returns the MediaOut, or None."""
    media_outs = comp.GetToolList(False, "MediaOut") or {}
    if not media_outs:
        return None
    media_out = list(media_outs.values())[0]
    try:
        media_out.Input.ConnectTo(source.Output)
    except Exception:
        media_out.Input = source
    return media_out


def build(comp, setting_path, line_no):
    comp.Lock()
    comp.StartUndo("Lyric Chunker: build Line %d" % line_no)
    try:
        comp.Paste(read_setting_table(setting_path))
        source = output_tool_for_line(comp, line_no)
        if source is None:
            print("[Lyric Chunker] pasted, but could not find the chain end "
                  "for Line %d — wire the last Merge to MediaOut by hand"
                  % line_no)
            return False
        if connect_to_media_out(comp, source) is None:
            print("[Lyric Chunker] pasted and found %s, but this comp has no "
                  "MediaOut — add one and connect it" % source.Name)
            return False
        print("[Lyric Chunker] Line %d built: %s -> MediaOut"
              % (line_no, source.Name))
        return True
    finally:
        comp.EndUndo(True)
        comp.Unlock()


def main():
    comp = get_comp()
    if comp is None:
        print("[Lyric Chunker] no current composition — open the Fusion page "
              "on a Fusion Composition clip and run this again")
        return

    root = OUTPUT_ROOT or comp.GetData("LyricChunker.Root") or ""
    line_text = ""
    if not OUTPUT_ROOT:
        answer = ask_for_input(comp, root)
        if answer is None:
            return
        root, line_text = answer

    settings = find_settings(root)
    if not settings:
        print("[Lyric Chunker] no Line#.setting files under %r — run "
              "Generate Fusion Comps in Blender first" % root)
        return
    comp.SetData("LyricChunker.Root", root)

    if line_text:
        try:
            line_no = int(line_text)
        except ValueError:
            print("[Lyric Chunker] %r is not a line number" % line_text)
            return
    else:
        line_no = min(settings)
        print("[Lyric Chunker] no line given — using the lowest found (%d). "
              "Available: %s"
              % (line_no, ", ".join(str(n) for n in sorted(settings))))

    if line_no not in settings:
        print("[Lyric Chunker] no .setting for Line %d. Available: %s"
              % (line_no, ", ".join(str(n) for n in sorted(settings))))
        return

    build(comp, settings[line_no], line_no)


main()
