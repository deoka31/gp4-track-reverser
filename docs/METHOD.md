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

## Closing segment and start line (0.9.4)

Every original ring has a closing segment (last point -> point 0) that is not like the others: normal segments step
262144 units along the heading, the closing segment steps *backwards* by 41k to 247k units (point 0 lies inside the
last normal segment, so the ring overlaps itself by 0.6 to 4.6 m). GP4 Builder shows this as an overlap at the end of
the ring. The game copes with it at the end of the lap.

Plain mirroring puts that segment between point 0 and point 1, directly behind the start line: the car crosses the line and
drives onto a segment that jumps back by up to 4 m (visible as a jump at the finish line and as odd computer car lines
in the first segments; worst on 02 Sepang and 03 Interlagos). GP4 Builder additionally shows a gap before sector 0 (it
does not draw the wrap segment, which is a normal segment now).

Fix: after mirroring, the arrays of the main ring are renumbered by one segment (`rotate_ring`) so that the short
segment is the closing one again. Everything that is indexed by segment moves with it: width/bank/boundary values, kerb
groups, pit joins (86/87), the DE/DF range, cameras, racing line sections, start position, heading and gradient in the
track header. The start line therefore moves back by the length of the short segment. The first `hd` values of the
ring change with the numbering; this works (changing `hd[0]` by hand to close the heading error is what crashed the
game earlier). `auto_rotation()` decides: rotate when the closing step is below 0.9 of a normal step and no kerb would
start at the line.

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

For the 17 original tracks the result is delivered in `racing_lines\S1CTnn.json` (computed for the moved start line)
and used if the SHA-1 of the source file matches and the start line is moved.

## Not stored in the track file

Some behaviour is fixed per track inside GP4.exe or in other archives and is not changed by this tool; see
KNOWN_ISSUES.md. Findings about the file formats are documented in the gp4-decomp project
(`docs/formats/circuit-dat.md`).


## Corner table check (0.9.6)

When a track is compiled the game builds a corner table from the racing line (apexes where the line comes within
`half width - 1EDh` of an edge, turn-in, exit). For every corner it divides by the number of exit segments; a line whose
corner ends exactly on its last apex gives a division by zero and the game crashes before the race (log: `[TC] CC line created`,
then `EXCEPTION_INT_DIVIDE_BY_ZERO` at 0x0043F7D8). `corner_check.py` runs the real builder (GP4.exe 0x0043FC0C) in Unicorn
on the reversed segment array (placed at the fixed address 0x008943A0) and reports whether it survives.
The AI also takes its corner speed from the radius of the line (`seg+0C8h`), so the radius of a fitted line should not be
larger than the original radius at the same place.
