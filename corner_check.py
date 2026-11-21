"""Corner table check: runs the game's own corner table builder (RLCorner_BuildCornerTable_Main,
GP4.exe 0x43fc0c) in Unicorn on a reversed track and its racing line.

The game builds a corner table (apexes, turn-in, exit) from the racing line while it compiles the track.
For some line shapes this crashes at 0x43f7d8 (division by zero: a corner with 0 exit segments).
This check finds such lines before they reach the game. Needs "pip install unicorn" and GP4.exe.
"""
import struct

import racing_line_fit as U

BUILD = 0x43FC0C
GAME_SEG = 0x8943A0        # the builder addresses the main segment array at this fixed address


def check(j1, secs, exe, core):
    """j1: reversed track JSON, secs: racing line sections. Returns (ok, message)."""
    from unicorn import UcError
    U.configure(exe, core, len(core.read_track(core.split_groups(j1['main_stream']), True)['hd']), 0)
    T = U.track_from_json(j1, core)
    N = T['N']
    sim = U.Sim()
    saved = U.SEG
    U.SEG = GAME_SEG
    try:
        sim.setup_track(T)
        sim.run(secs)
        mu = sim.mu
        for p in range(N):
            b = GAME_SEG + p * U.SEGSZ
            mu.mem_write(b + 0x60, struct.pack('<H', T['Wn'][p] & 0xFFFF))
            mu.mem_write(b + 0x62, struct.pack('<H', T['Wp'][p] & 0xFFFF))
            for off, n in ((0x51, 1), (0x73, 1), (0x8C, 1), (0xA8, 1), (0xB6, 1), (0x134, 2)):
                mu.mem_write(b + off, b'\0' * n)
        mu.mem_write(0x627A9C, struct.pack('<I', 0xCCC))                 # g_nRLBand_CentreShareQ14
        mu.mem_write(0x86855C, struct.pack('<H', j1['track_header']['flags'] & 0xFFFF))
        mu.mem_write(0x627B08, struct.pack('<I', 0x80))                  # g_nRLCorner_EdgeMarginExtra_Hdr8000
        sp = U.STACK + 0x8000 - 4
        ret = 0x41000000
        mu.mem_write(sp, struct.pack('<I', ret))
        mu.reg_write(U.UC_X86_REG_ESP, sp)
        try:
            mu.emu_start(BUILD, ret, count=20_000_000)
        except UcError as e:
            return False, 'the game would crash while building the corner table (%s)' % e
        return True, 'corner table OK'
    finally:
        U.SEG = saved
