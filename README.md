# GP4 track reverser

Turns a **Grand Prix 4** track file (`S1CTnn.DAT`) around so that the circuit is driven in the opposite direction.
Works for the 17 original tracks and, with a computed racing line, for other track files.

> **Status: 0.9.1 beta.** All 17 original tracks start and can be driven, but each has small physical or visual
> problems. See [KNOWN_ISSUES.md](KNOWN_ISSUES.md). Please report what you find (see below).

No game files are included. You need your own copy of Grand Prix 4.

## Requirements

- Python 3.8 or newer. Nothing else for the 17 original tracks.
- For other track files (mods): `pip install unicorn` and the original `GP4.exe` (the racing line is computed with the
  game's own code; takes about 4-8 minutes per track).

## Usage

Unpack the folder anywhere below your GP4 folder (for example `Grand Prix 4\Reverser`). In a command prompt:

    python reverse_track.py all              all 17 original tracks 
    python reverse_track.py 03 07 12          single tracks by number
    python reverse_track.py D:\mod\S1CT21.DAT any track file (needs unicorn and GP4.exe)

For the original tracks the tool also writes `reversed\anim.wad`, a copy of the game's `anim.wad` in which the pit crew
side is turned for the reversed tracks. Copy it next to `GP4.exe` (back up the original first) when you play reversed
tracks; restore the original for the normal tracks.

Options: `--gp4 FOLDER` (GP4 folder with `Circuits\`), `--src FOLDER` (folder with the untouched originals; also found automatically in `Circuits*` folders such as `Circuits Orig`), `--out FOLDER` (default `reversed\`), `--version`.

The result is `reversed\S1CTnn.DAT`. **Nothing is ever written to `Circuits\`.** To play, back up the original
`Circuits\S1CTnn.DAT` and copy the reversed file over it. The source must be the untouched original: `Circuits\S1CTnn.DAT`, `S1CTnno.DAT` or a folder like `Circuits Orig`
(checked by SHA-1, so a reversed file is never reversed again by mistake).

## How it works (short)

The track file contains the main track, the pit lane, the start grid side, the cameras and the racing line (the line the
computer cars follow). The tool mirrors all of them. The racing line cannot simply be mirrored: it is a chain of
sections in which every section continues where the previous one stopped. It is therefore re-fitted by running the
game's own routine in an emulator. Details: [docs/METHOD.md](docs/METHOD.md).

## Reporting problems

Please open a GitHub issue with the **Bug report** template. The most useful details:

- track number and name, tool version (`python reverse_track.py --version`)
- where on the track (corner name or segment, lap/pit lane), and what happens
- type: physics, graphics, pit lane / pit stop, computer cars, crash, tool error
- a screenshot if it is visual; for tool errors the complete text of the command prompt
- whether the track came from the 17 originals (ready-made racing line) or was computed

## Versions

Versions follow [SemVer](https://semver.org): `0.9.x` = beta, `1.0.0` = first release after the beta has been checked,
`1.0.1` = bug fixes, `1.1.0` = new features. See [CHANGELOG.md](CHANGELOG.md).

## License

MIT, see [LICENSE](LICENSE). Grand Prix 4 is a trademark of its owners; this project is not affiliated with them.
