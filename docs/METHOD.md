# Method

## Track file

`S1CTnn.DAT` = 0x20 byte header, data, two 16-bit checksums. The data holds: object table, track header, a main track
command stream (one section per segment, each with heading, centre, width, bank, kerb and boundary commands), the racing
line stream, the pit lane command stream, the camera section and the grid file name (`gridline.jip` / `gridleft.jip`).
`gp4track.py` reads this into JSON and writes it back byte-identically (`python gp4track.py check S1CT*.DAT`); on
writing it recalculates offsets, length and checksums.

## Mirroring

For a ring of N points, reversed point j is original point `(N - j) % N`, and reversed segment i is original segment
`N - 1 - i`. The pit lane is a linear array of NP segments: segment `NP - 2 - i`.

- headings turn by half a circle, lateral values and bank angle change sign
- the two widths, the two boundary lines, the two kerb commands and the kerb profile slots swap sides
- header: start heading + 180 degrees, start gradient negated, pit side and pole side flag bits toggle, grid file swapped
- pit stream marks swap in pairs: pit lane leaves / rejoins (9B/9E), pit zone start / end (9F/A0), the two marks for the
  pit stop state machine (96/97), first box / area end (89/F1); the first box mark sits at `NP - 1 - F1` so that every
  box keeps its place relative to its building
- pit entry / exit joins in the main stream (86/87) swap
- cameras are mirrored by segment number

## Heading integration and the pit lane (0.9.2)

The game does not store an absolute heading per segment. While loading it builds the track by adding up the per segment
turn values `hd` starting at the start heading; this integrated heading (`seg+0`, 16 bit angle) is what the car
model uses to turn world positions into the local track position (progress along the lane). The absolute heading
(chord to the next segment) is only used for drawing and AI. In the original files both agree exactly. The main ring
carries its closing error in `hd[N-1]`, and the pit lane is built from the main track state saved at the pit entry join
(command 86).

After mirroring, the integrated heading of the reversed file drifts from the absolute heading (Imola: 1.6 degrees at
the seam of the main ring plus 0.3 degrees at the start of the pit lane). A car parked 4 to 6 m beside the lane then
gets a local progress that is too small by `lateral * sin(error)`, a few tens of units. The pit stop gate
(`PitBox_CheckStopZoneRace`) needs progress >= 0x1E00 at the stop point; with the error the stop point maps to about
0x1D78, the car is never accepted as arrived, its speed never drops below the limit of the state machine and the crew
never starts. That was the cause of stuck pit stops on Imola, Nuerburgring, Magny-Cours, Spa and Suzuka.

Fix: `hd[0]` of the pit lane is recalculated so that the integrated pit heading matches the absolute heading at the
join (`_align_pit_heading`). The main track `hd` is deliberately left alone: changing `hd[0]` of the main ring made the
game crash at load. `heading_check()` reports the largest deviation between integrated and absolute pit heading in
degrees (about 0 for the originals and for tool output, printed by `reverse_track.py`).

## Racing line

The racing line is stored as sections. The game runs a small state machine over the track segments (radius, arc centre,
lateral offset, heading) and each section changes that state. A mirrored line therefore cannot be written down directly.
The tool:

1. mirrors the original line into a target (lateral offset and heading per segment),
2. runs the game's own routine `RacingLine_BuildIntoSegments` (GP4.exe, 0x0040abc1) in an x86 emulator (`unicorn`) to
   learn exactly what each candidate section produces,
3. searches (beam search) for a section list whose output follows the target and stays on the track,
4. checks the constraints the game needs: the section lengths sum to N - 1, the game must not rewrite the stream.

Where the fit would diverge (tight street circuits) a section with start values resets the state.

For the 17 original tracks the result is delivered in `racing_lines\S1CTnn.json` and used if the SHA-1 of the source file
matches.

## Not stored in the track file

Some behaviour is fixed per track inside GP4.exe or in other archives and is not changed by this tool; see
KNOWN_ISSUES.md. Findings about the file formats are documented in the gp4-decomp project
(`docs/formats/circuit-dat.md`).
