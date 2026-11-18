#!/usr/bin/env python3
"""gp4track.py - read and write GP4 track files (circuits\\s1ctNN.dat).

    python tools/gp4track.py dump  S1CT07.DAT  s1ct07.json
    python tools/gp4track.py build s1ct07.json S1CT07_new.DAT
    python tools/gp4track.py check "E:/Programme/Grand Prix 4/Circuits"/S1CT*.DAT
    python tools/gp4track.py info  S1CT07.DAT

dump   turns the file into a readable JSON file (one entry per section,
       track command and racing line section).
build  writes a track file from such a JSON file. Offsets in the file
       header, the data length and the two checksums are recalculated, so
       a JSON file can be edited (values changed, commands added or
       removed) and built again.
check  dump + build in memory for each file and compare byte by byte with
       the original. Prints OK or the first differing byte.
info   short summary (segments, racing line sections, cameras).

The layout follows docs/formats/circuit-dat.md and the loader code
(UnpackTrackDataBlock, InitialiseRaceSession, TrackBuild_ParseSectorAnd-
CmdStream, RacingLine_DecodeNextSection_ESI_CF, TrackCam_ParseCamera-
Records_ESI). Parts whose meaning is still open are kept as raw values or
hex bytes, so nothing is lost.

This tool contains no game data. You need your own track files.
"""
import json
import struct
import sys

# ---------------------------------------------------------------------------
# Argument bytes of the track commands 80h..F7h (from the handler table
# g_apfnTrackCmdHandlers). Only needed for reading: when building, the
# words listed in the JSON are written as they are.
ARG_BYTES = {
    0x80: 2, 0x81: 2, 0x82: 2, 0x83: 0, 0x84: 0, 0x85: 4, 0x86: 0, 0x87: 0,
    0x88: 2, 0x89: 2, 0x8a: 10, 0x8b: 10, 0x8c: 2, 0x8d: 2, 0x8e: 4, 0x8f: 4,
    0x90: 2, 0x91: 2, 0x92: 4, 0x94: 2, 0x95: 2, 0x96: 0, 0x97: 0, 0x98: 2,
    0x99: 2, 0x9a: 4, 0x9b: 0, 0x9c: 12, 0x9e: 0, 0x9f: 0, 0xa0: 0, 0xa1: 0,
    0xa2: 0, 0xa3: 0, 0xa4: 0, 0xa6: 4, 0xa7: 4, 0xa8: 0, 0xa9: 2, 0xaa: 6,
    0xab: 4, 0xac: 8, 0xad: 4, 0xae: 2, 0xaf: 4, 0xb0: 6, 0xb1: 2, 0xb2: 2,
    0xb4: 4, 0xb5: 4, 0xb6: 2, 0xb7: 2, 0xb8: 6, 0xba: 4, 0xbd: 4, 0xbe: 4,
    0xbf: 4, 0xc0: 2, 0xc1: 2, 0xc2: 4, 0xc3: 4, 0xc4: 6, 0xc5: 12, 0xc6: 2,
    0xc7: 4, 0xc8: 14, 0xc9: 16, 0xca: 12, 0xcc: 4, 0xcd: 6, 0xce: 2, 0xcf: 2,
    0xd0: 4, 0xd1: 0, 0xd2: 2, 0xd3: 2, 0xd4: 0, 0xd5: 2, 0xd6: 0, 0xd7: 0,
    0xd8: 0, 0xd9: 2, 0xdb: 0, 0xdc: 2, 0xdd: 4, 0xde: 6, 0xdf: 6, 0xe0: 6,
    0xe1: 2, 0xe2: 2, 0xe3: 4, 0xe4: 4, 0xe5: 4, 0xe6: 4, 0xe7: 24, 0xe8: 18,
    0xe9: 18, 0xea: 2, 0xeb: 2, 0xec: 2, 0xed: 2, 0xee: 40, 0xef: 8, 0xf0: 12,
    0xf1: 0, 0xf2: 8, 0xf3: 8, 0xf4: 14, 0xf5: 14, 0xf6: 12, 0xf7: 16,
}

# Short labels for the commands the original tracks use (see
# docs/formats/circuit-dat.md). Only a help for reading the JSON.
CMD_NOTE = {
    0x86: 'pit entry join', 0x87: 'pit exit join', 0x89: 'first pit box',
    0xad: 'bank angle', 0xae: 'edge strip flags', 0xb4: 'width neg side',
    0xb5: 'width pos side', 0xbd: 'sun angles', 0xca: 'kerb profile',
    0xcc: 'backdrop angle?', 0xde: 'edge speed value neg side',
    0xdf: 'edge speed value pos side', 0xef: 'absolute coordinate mode',
    0xf0: 'absolute heading', 0xf2: 'kerb neg side', 0xf3: 'kerb pos side',
    0xf4: 'boundary line start', 0xf5: 'boundary line end',
    0xf6: 'absolute centre X/Y/Z', 0xf7: 'edge strip values',
}

HDR_FIELDS = ['start_heading', 'start_gradient', 'start_x', 'start_y',
              'start_z', 'start_width', 'pole_side_word', 'flags',
              'word_10', 'list_count']

CAM_RECORD_BYTES = 38
FILE_HDR_BYTES = 0x20


def checksums(data):
    """The two 16-bit sums checked by File_VerifyTrailingChecksums_CF."""
    s = r = 0
    for b in data:
        r = ((r << 3) | (r >> 13)) & 0xFFFF
        s = (s + b) & 0xFFFF
        r = (r + b) & 0xFFFF
    return s, r


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


class Reader:
    def __init__(self, data, pos=0):
        self.d = data
        self.pos = pos

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.pos)[0]
        self.pos += 2
        return v

    def words(self, n):
        v = list(struct.unpack_from('<%dh' % n, self.d, self.pos))
        self.pos += 2 * n
        return v


# ---------------------------------------------------------------------------
# Reading

def read_cmd_stream(r, flags, state):
    """Track command stream up to FFFFh. state['abs'] follows command EFh."""
    items = []
    while True:
        w = r.u16()
        if w == 0xFFFF:
            return items
        if w < 0x8000:
            items.append({'sec': w, 'words': r.words(4)})
            continue
        op = 0x80 + ((w >> 8) & 0x7F)
        if op not in ARG_BYTES:
            raise ValueError('unknown track command %02X at %X' % (op, r.pos - 2))
        n = ARG_BYTES[op]
        if op == 0xC5 and flags & 0x200:
            n = 14
        if op == 0xEF:
            state['abs'] = True
        if op == 0xCA and state['abs']:
            n = 16 if flags & 0x20 else 14
        item = {'cmd': '%02X' % op, 'seg': w & 0xFF, 'args': r.words(n // 2)}
        if op in CMD_NOTE:
            item['note'] = CMD_NOTE[op]
        items.append(item)


def read_racing_line(r):
    """Racing line sections (RacingLine_DecodeNextSection_ESI_CF), up to 0."""
    secs = []
    while True:
        h = r.u16()
        if h == 0:
            return secs
        s = {'len': h & 0x7FF, 'flags': '%04X' % (h & 0xF800)}
        if h & 0x8000:
            s['lateral'], s['heading'] = r.words(2)
        s['cx'] = r.words(1)[0]

        def radius():
            if h & 0x4000:
                hi, lo = struct.unpack_from('<hH', r.d, r.pos)
                r.pos += 4
                return (hi << 16) | lo
            return r.words(1)[0]
        s['radius'] = radius()
        if h & 0x2000:
            s['end_radius'] = radius()
        secs.append(s)


def dump(raw):
    data = raw[FILE_HDR_BYTES:-4]
    hdr = struct.unpack_from('<8I', raw, 0)
    if hdr[2] != len(data):
        raise ValueError('data length in header %X, file has %X' % (hdr[2], len(data)))
    if checksums(raw[:-4]) != struct.unpack_from('<HH', raw, len(raw) - 4):
        raise ValueError('checksums do not match')
    if hdr[4] != 0x110 or hdr[7] != 0:
        raise ValueError('unusual header (+10h = %X, relocations %d)' % (hdr[4], hdr[7]))
    out = {
        'format': 'gp4track 1',
        'file_header': {'old_base': '%X' % hdr[0], 'dword_04': hdr[1],
                        'dword_0c': hdr[3]},
        'objects_hex': data[:0x110].hex(),
    }
    r = Reader(data, 0x110)
    th = dict(zip(HDR_FIELDS, r.words(10)))
    flags = th['flags'] & 0xFFFF
    out['track_header'] = th
    lst = []
    for _ in range(th['list_count']):
        c = r.u16()
        lst.append([c] if c == 0x1F else [c, r.u16()])
    out['header_list'] = lst
    state = {'abs': False}
    out['main_stream'] = read_cmd_stream(r, flags, state)
    out['racing_line'] = read_racing_line(r)
    pad = data[r.pos:hdr[6]]
    out['padding'] = {'zeros': len(pad)} if not any(pad) else {'hex': pad.hex()}
    r.pos = hdr[6]
    out['pit_stream'] = read_cmd_stream(r, flags, state)
    if r.pos != hdr[5]:
        raise ValueError('pit stream ends at %X, cameras at %X' % (r.pos, hdr[5]))
    cams = []
    while struct.unpack_from('<H', data, r.pos)[0] != 0xFFFF:
        cams.append(data[r.pos:r.pos + CAM_RECORD_BYTES].hex())
        r.pos += CAM_RECORD_BYTES
    r.pos += 2
    out['cameras_hex'] = cams
    out['after_cameras_16_hex'] = data[r.pos:r.pos + 16].hex()
    r.pos += 16
    names = []
    for _ in range(r.u16()):
        e = data.index(b'\0', r.pos)
        names.append(data[r.pos:e].decode('latin-1'))
        r.pos = e + 1
    out['file_names'] = names
    if r.pos != len(data):
        raise ValueError('%d bytes left at the end' % (len(data) - r.pos))
    return out


# ---------------------------------------------------------------------------
# Writing

def w16(buf, *vals):
    for v in vals:
        buf += struct.pack('<H', int(v) & 0xFFFF)


def write_cmd_stream(buf, items):
    for it in items:
        if 'sec' in it:
            if not 0 <= it['sec'] < 0x8000 or len(it['words']) != 4:
                raise ValueError('bad section %r' % it)
            w16(buf, it['sec'], *it['words'])
        else:
            op = int(it['cmd'], 16)
            w16(buf, ((op - 0x80) << 8 | 0x8000) | (it['seg'] & 0xFF), *it['args'])
    w16(buf, 0xFFFF)


def write_racing_line(buf, secs):
    for s in secs:
        h = int(s['flags'], 16) | (s['len'] & 0x7FF)
        w16(buf, h)
        if h & 0x8000:
            w16(buf, s['lateral'], s['heading'])
        w16(buf, s['cx'])
        for key in ('radius', 'end_radius'):
            if key == 'end_radius' and not h & 0x2000:
                continue
            v = int(s[key])
            if h & 0x4000:
                w16(buf, (v >> 16), v)
            else:
                w16(buf, v)
    w16(buf, 0)


def build(j):
    if j.get('format') != 'gp4track 1':
        raise ValueError('not a gp4track JSON file')
    d = bytearray(bytes.fromhex(j['objects_hex']))
    if len(d) != 0x110:
        raise ValueError('objects_hex must be 110h bytes')
    th = j['track_header']
    th['list_count'] = len(j['header_list'])
    w16(d, *[th[k] for k in HDR_FIELDS])
    for e in j['header_list']:
        w16(d, *e)
    write_cmd_stream(d, j['main_stream'])
    write_racing_line(d, j['racing_line'])
    pad = j['padding']
    d += bytes(pad['zeros']) if 'zeros' in pad else bytes.fromhex(pad['hex'])
    pit_ofs = len(d)
    write_cmd_stream(d, j['pit_stream'])
    cam_ofs = len(d)
    for c in j['cameras_hex']:
        b = bytes.fromhex(c)
        if len(b) != CAM_RECORD_BYTES:
            raise ValueError('camera record must be %d bytes' % CAM_RECORD_BYTES)
        d += b
    w16(d, 0xFFFF)
    d += bytes.fromhex(j['after_cameras_16_hex'])
    w16(d, len(j['file_names']))
    for n in j['file_names']:
        d += n.encode('latin-1') + b'\0'
    fh = j['file_header']
    head = struct.pack('<8I', int(fh['old_base'], 16), fh['dword_04'], len(d),
                       fh['dword_0c'], 0x110, cam_ofs, pit_ofs, 0)
    raw = head + bytes(d)
    raw += struct.pack('<HH', *checksums(raw))
    if len(raw) > 200000:
        print('warning: %d bytes, the game accepts at most 200000' % len(raw))
    return raw


# ---------------------------------------------------------------------------

def info(j):
    main_segs = sum(1 for i in j['main_stream'] if 'sec' in i)
    pit_segs = sum(1 for i in j['pit_stream'] if 'sec' in i)
    seg_words = sum(i['sec'] for i in j['main_stream'] if 'sec' in i)
    rl = sum(s['len'] for s in j['racing_line'])
    print('main track: %d sections, %d segments' % (main_segs, seg_words))
    print('pit lane:   %d sections' % pit_segs)
    print('racing line: %d sections over %d segments' % (len(j['racing_line']), rl))
    print('cameras: %d, files: %s' % (len(j['cameras_hex']), ', '.join(j['file_names'])))


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == 'dump' and len(argv) == 4:
        j = dump(open(argv[2], 'rb').read())
        with open(argv[3], 'w') as f:
            json.dump(j, f, indent=1)
        print('wrote', argv[3])
    elif cmd == 'build' and len(argv) == 4:
        raw = build(json.load(open(argv[2])))
        open(argv[3], 'wb').write(raw)
        print('wrote %s (%d bytes)' % (argv[3], len(raw)))
    elif cmd == 'info':
        for p in argv[2:]:
            print('==', p)
            info(dump(open(p, 'rb').read()))
    elif cmd == 'check':
        bad = 0
        for p in argv[2:]:
            raw = open(p, 'rb').read()
            try:
                # through JSON text, as a user would edit it
                new = build(json.loads(json.dumps(dump(raw))))
            except ValueError as e:
                print('FAIL ', p, e)
                bad += 1
                continue
            if new == raw:
                print('OK   ', p, '(%d bytes identical)' % len(raw))
            else:
                i = next((k for k in range(min(len(new), len(raw))) if new[k] != raw[k]),
                         min(len(new), len(raw)))
                print('FAIL ', p, 'first difference at byte %X' % i)
                bad += 1
        return 1 if bad else 0
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
