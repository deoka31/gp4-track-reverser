# Known issues

Status of version **0.9.6-beta**.

| # | Issue | Tracks | Status |
|---|---|---|---|
| 1 | The pit crew appears on the wrong side of the pit lane (not coming from the garage). | all 17 | fixed in 0.9.1 by the patched `anim.wad` copy the tool writes; confirmed in the game |
| 2 | Pit stop: the car stops at its box but the crew never starts the stop. | 04, 09, 10, 14, 17 | fixed in 0.9.2 (pit lane heading alignment); pit stops work on all 17 tracks, confirmed in the game |
| 3 | Converting a mod track fails with `ValueError: pit stream ends at ..., cameras at ...` | mod tracks | fixed in 0.9.1; converting mod tracks works, confirmed |
| 4 | Small physical and visual problems at places (e.g. computer cars brushing the edge, odd curb or wall pieces). | all 17 | open, please report places |
| 5 | The racing line follows the mirrored original line only approximately: mean deviation 43-90 units (about 20-40 cm); a few segments lie slightly outside the asphalt (up to 1.4 times the half width). | all 17 | open, improvement planned |
| 6 | Jump at the finish line (Interlagos, Sepang worst) and odd computer car lines behind the start. | all 17 | fixed in 0.9.4 (start line moved back by one segment); confirmed on 02, 03, 04. A very small remaining graphical blip at the line on 03 may be visible; not physical. |
| 7 | 14 Spa: computer cars had trouble in the Bus Stop chicane (too fast into the second element, then over the kerb). Cause: the fitted racing line had a larger radius there than the original (about 10150 instead of 9000), and the game derives the AI corner speed from the line radius. Fixed by setting the radius of segments 76-84 to 9500 (confirmed in the game: the cars now take the chicane). | 14 | fixed in 0.9.6 |
| 8 | 07 Monaco: cars run with two wheels outside the track in some corners (graphical); at the tight hairpin there is sometimes physical contact with the wall. | 07 | open |
| 9 | Mod tracks: the racing line is computed, and its radius in a corner can be larger than in the original line. The computer cars take the corner faster then (this was the cause of the Spa problem). Not predictable; found only by testing. | mod tracks | open; the line of an affected corner can be adjusted by hand as was done for 14 Spa |

Values that live in the game's EXE and not in the track file (for example the pit lane time to the first box) stay
those of the original driving direction. They cannot be changed by this tool.
