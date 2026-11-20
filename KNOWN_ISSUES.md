# Known issues

Status of version **0.9.3-beta** (reported by the first tester, all 17 original tracks).

| # | Issue | Tracks | Status |
|---|---|---|---|
| 1 | The pit crew appears on the wrong side of the pit lane (not coming from the garage). | all 17 | fixed in 0.9.1 by the patched `anim.wad` copy the tool writes; confirmed in the game |
| 2 | Pit stop: the car stops at its box but the crew never starts the stop. | 04, 09, 10, 14, 17 | fixed in 0.9.2 (pit lane heading alignment); pit stops work on all 17 tracks, confirmed in the game |
| 3 | Converting a mod track fails with `ValueError: pit stream ends at ..., cameras at ...` | mod tracks | fixed in 0.9.1; converting mod tracks works, confirmed |
| 4 | Small physical and visual problems at places (e.g. computer cars brushing the edge, odd curb or wall pieces). | all 17 | open, please report places |
| 5 | The racing line follows the mirrored original line only approximately: mean deviation 43-90 units (about 20-40 cm); a few segments lie slightly outside the asphalt (up to 1.4 times the half width). | all 17 | open, improvement planned |

Values that live in the game's EXE and not in the track file (for example the pit lane time to the first box) stay
those of the original driving direction. They cannot be changed by this tool.
