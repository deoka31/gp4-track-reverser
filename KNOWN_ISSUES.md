# Known issues

Status of version **0.9.0-beta** (reported by the first tester, all 17 original tracks).

| # | Issue | Tracks | Status |
|---|---|---|---|
| 1 | The pit crew appears on the wrong side of the pit lane (not coming from the garage). | all 17 | cause found, fix in 0.9.1 (the side is stored in `anim.wad`, not in the track file) |
| 2 | Pit stop: the car stops at its box but the crew never starts the stop. | 04 Imola, 09 Nuerburgring, 10 Magny-Cours, 14 Spa, 17 Suzuka | under investigation; first box was one segment off (fixed in 0.9.1), crew side probably involved |
| 3 | Converting a mod track fails with `ValueError: pit stream ends at ..., cameras at ...` | mod tracks | fixed in 0.9.1 |
| 4 | Small physical and visual problems at places (e.g. computer cars brushing the edge, odd curb or wall pieces). | all 17 | open, please report places |
| 5 | The racing line follows the mirrored original line only approximately: mean deviation 43-90 units (about 20-40 cm); a few segments lie slightly outside the asphalt (up to 1.4 times the half width). | all 17 | open, improvement planned |

Values that live in the game's EXE and not in the track file (for example the pit lane time to the first box) stay
those of the original driving direction. They cannot be changed by this tool.
