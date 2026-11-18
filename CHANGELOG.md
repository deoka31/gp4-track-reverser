# Changelog

## 0.9.1-beta
- File and folder names are English now: `reverse_track.py` (was `umkehren.py`), `reverse_core.py`, `racing_line_fit.py`, `racing_lines\`, output folder `reversed\`, command `all`.
- Pit crew side: the side is stored in `anim.wad` (first line of `AnimationData\<track>2001.anm`), not in the track file.
  The tool now writes a patched COPY of `anim.wad` next to the reversed tracks (`reversed\anim.wad`, only the one digit
  of each reversed track changes; set from the reversed file's own pit side flag, so it also works for single tracks, several runs one after another and mod tracks named `S1CTnn.DAT`). The original `anim.wad` is never modified. Copy it into the game folder while you
  play reversed tracks and put the original back afterwards.
- Pit box alignment: the first box mark was one segment too early after mirroring; every box was one segment off its
  building. Fixed. This may also fix the stuck pit stops (needs testing, see KNOWN_ISSUES.md).
- The tool checks (SHA-1) that the source of an original track is really the untouched file. If `Circuits\S1CTnn.DAT`
  was already overwritten by a reversed track it looks into other `Circuits*` folders (e.g. `Circuits Orig`) or `--src`,
  instead of failing with `Rennlinie deckt nicht den ganzen Ring ab`.
- Mod track files are accepted now: a leftover block before the pit stream with a wrong header pointer (`+14h`, the game
  never reads it), a `#GP4INFO|...#` text at the end of the file, pit stream with command 88 instead of 89, and width /
  boundary values that jump at the start line.

## 0.9.0-beta
- First public state: reverses all 17 original tracks (`python reverse_track.py all`), ready-made racing lines for the
  originals, computed racing line for other files (needs unicorn and GP4.exe).
- All 17 reversed tracks start and run without crashing in the game; known problems are listed in KNOWN_ISSUES.md.
