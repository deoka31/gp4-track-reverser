#!/usr/bin/env python3
"""GP4 track reverser: turns a Grand Prix 4 track so that it is driven in the other direction.

Examples (run inside the tool folder, which may sit anywhere below the GP4 folder):
    python reverse_track.py 03            Interlagos (Circuits\\S1CT03o.DAT or S1CT03.DAT) -> reversed\\S1CT03.DAT
    python reverse_track.py 01 05 12      several tracks
    python reverse_track.py all           all 17 original tracks
    python reverse_track.py C:\\mod\\S1CT21.DAT     any track file (the racing line is then computed, needs unicorn)

Options:
    --gp4 FOLDER    GP4 folder containing Circuits\\ (default: searched above this folder)
    --src FOLDER    folder with the untouched original files (default: Circuits, then Circuits* folders)
    --out FOLDER    output folder (default: .\\reversed)

The output is never written to the Circuits folder. For the 17 original tracks the racing line comes ready-made from
the folder racing_lines\\. For other tracks (mods) it is computed: this needs "pip install unicorn" and GP4.exe.
"""
import sys, os, re, json, glob, hashlib, argparse
sys.dont_write_bytecode = True
__version__ = '0.9.3-beta'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gp4track as gt
import reverse_core as q

# The old approximate racing line of the source module is not used (it crashed the game); a placeholder is built and
# replaced by the exactly fitted line afterwards.
q.anchored_line = lambda g, p, N, chain=True: ([{'len': N - 1, 'flags': '5000', 'cx': 0, 'radius': 0}], {})


def find_gp4():
    d = HERE
    for _ in range(5):
        if os.path.isdir(os.path.join(d, 'Circuits')):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(os.path.join(HERE, '..'))


def known_sha1(nn):
    p = os.path.join(HERE, 'racing_lines', 'S1CT%s.json' % nn)
    return json.load(open(p)).get('source_sha1') if os.path.isfile(p) else None


def find_source(gp4, key, src_dir=None):
    """key: '03' or a file path -> path of the ORIGINAL source file.

    For the 17 original tracks the file must be the untouched original (checked by SHA-1): the tool looks in
    --src, then Circuits\\S1CTnno.DAT / S1CTnn.DAT, then every folder "Circuits*" next to it (e.g. "Circuits Orig").
    A Circuits file that was overwritten by a reversed track is skipped."""
    if os.path.isfile(key):
        return key
    nn = key.zfill(2)
    want = known_sha1(nn)
    dirs = [src_dir] if src_dir else []
    dirs.append(os.path.join(gp4, 'Circuits'))
    try:
        dirs += [os.path.join(gp4, d) for d in sorted(os.listdir(gp4)) if d.lower().startswith('circuits')]
    except OSError:
        pass
    first = None
    for d in dirs:
        # 'o' = untouched original variant (in case someone changed the normal file by hand)
        for nm in ('S1CT%so.DAT' % nn, 'S1CT%s.DAT' % nn):
            p = os.path.join(d, nm)
            if os.path.isfile(p):
                first = first or p
                if want is None or hashlib.sha1(open(p, 'rb').read()).hexdigest() == want:
                    return p
    if first:
        print('  %s is not the original GP4 file (already reversed or modified).' % first)
        print('  Put the untouched original next to it (folder "Circuits Orig" or S1CT%so.DAT) or use --src FOLDER.' % nn)
    return None


def load_line(raw, key):
    p = os.path.join(HERE, 'racing_lines', 'S1CT%s.json' % os.path.basename(key)[4:6])
    if not os.path.isfile(p):
        return None
    d = json.load(open(p))
    if d.get('source_sha1') == hashlib.sha1(raw).hexdigest():
        return d['racing_line']
    return None


ANIM_NAMES = ['melborne', 'sepang', 'interlagos', 'imola', 'barcelona', 'a1ring', 'monaco', 'montreal', 'nurburgring',
              'magnycours', 'silverstone', 'hockenheim', 'hungaroring', 'spa', 'monza', 'indianapolis', 'suzuka']


def patch_anim_wad(gp4, outdir, sides):
    """sides: {track slot number: pit side bit of the REVERSED track file}.

    The pit crew side is the first line (0/1) of AnimationData\\<track>2001.anm inside anim.wad (GP4.exe
    AnimSys_ParseAnmFirstLine_PickSetupScript), not part of the track file. In the 17 originals it is 1 when the pit
    side bit (header flag 0x2) is clear and 0 when it is set. The digit is therefore set from the reversed file's own
    flag, so it is right for original and mod tracks alike. Several runs add up: an existing reversed\\anim.wad is
    extended, never started again from the original."""
    import struct
    orig = os.path.join(gp4, 'anim.wad')
    dst = os.path.join(outdir, 'anim.wad')
    src = dst if os.path.isfile(dst) else orig
    if not sides or not os.path.isfile(src):
        return False
    d = bytearray(open(src, 'rb').read())
    cnt = struct.unpack_from('<I', d, 0)[0]
    want = {'animationdata\\%s2001.anm' % ANIM_NAMES[n - 1]: n for n in sides if 1 <= n <= 17}
    done = {}
    for i in range(cnt):
        o = 4 + i * 0x88
        nm = bytes(d[o:o + 0x80]).split(b'\0')[0].decode('latin-1').lower()
        if nm in want:
            off = struct.unpack_from('<I', d, o + 0x80)[0]
            if d[off:off + 1] in (b'0', b'1'):
                d[off] = ord('0') if sides[want[nm]] else ord('1')
                done[want[nm]] = chr(d[off])
    os.makedirs(outdir, exist_ok=True)
    open(dst, 'wb').write(d)
    print('  anim.wad copy updated (crew side digit per track: %s) -> %s' % (sorted(done.items()), dst))
    return True


def reverse_one(src, gp4, outdir):
    raw = open(src, 'rb').read()
    name = os.path.basename(src)
    j0 = gt.dump(raw)
    if gt.build(json.loads(json.dumps(j0))) != raw:
        print('  ERROR: the file cannot be rebuilt byte-identically - skipped')
        return False
    j1 = q.reverse_json(j0)
    j1.pop('_line_report', None)
    secs = load_line(raw, name)
    how = 'ready-made from racing_lines\\'
    if secs is None:
        try:
            import racing_line_fit as U
            exe = os.path.join(gp4, 'GP4.exe')
            if not os.path.isfile(exe):
                raise FileNotFoundError(exe)
            print('  Computing the racing line (a few minutes) ...')
            _, secs, st = U.compute_line(j0, exe, q)
            how = 'computed (%d sections, mean deviation %.0f, outside the track: %d segments)' % (
                st['sections'], st['mean_error'], len(st['outside']))
        except ImportError:
            print('  No ready-made racing line for this file and "unicorn" is missing (pip install unicorn).')
            print('  Without a matching racing line the game would crash - file not written.')
            return False
        except FileNotFoundError as e:
            print('  GP4.exe not found: %s (use --gp4) - file not written.' % e)
            return False
    hc = q.heading_check(j1)
    print('  pit lane heading check: %.4f degrees%s' % (hc, '' if hc < 0.01 else ' - DEVIATION, pit stops may get stuck'))
    j1['racing_line'] = secs
    out = gt.build(j1)
    if gt.build(gt.dump(out)) != out:
        print('  ERROR: the result cannot be rebuilt stably')
        return False
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, 'S1CT%s.DAT' % name[4:6])
    if os.path.basename(os.path.dirname(os.path.abspath(dst))).lower() == 'circuits':
        print('  Aborted: writing into "Circuits" is blocked.')
        return False
    open(dst, 'wb').write(out)
    print('  -> %s (%d bytes), racing line: %s' % (dst, len(out), how))
    return (True, 1 if (j1['track_header']['flags'] & 2) else 0)    # (ok, pit side bit of the reversed file)


def main(argv):
    ap = argparse.ArgumentParser(description='GP4 track reverser %s' % __version__)
    ap.add_argument('strecken', nargs='+', help='track numbers (03), "all" or file paths')
    ap.add_argument('--gp4', default=find_gp4())
    ap.add_argument('--out', default=os.path.join(HERE, 'reversed'))
    ap.add_argument('--src', default=None, help='folder with the untouched original S1CTnn.DAT files')
    ap.add_argument('--version', action='version', version=__version__)
    a = ap.parse_args(argv[1:])
    print('GP4 track reverser %s' % __version__)
    keys = []
    for s in a.strecken:
        keys += ['%02d' % i for i in range(1, 18)] if s.lower() in ('all', 'alle') else [s]
    ok = 0
    sides = {}
    for k in keys:
        src = find_source(a.gp4, k, a.src)
        print('Track %s: %s' % (k, src))
        if src is None:
            print('  not found')
            continue
        res = reverse_one(src, a.gp4, a.out)
        if res:
            ok += 1
            m = re.match(r'S1CT(\d\d)', os.path.basename(src), re.I)     # slot number, also for mod files
            if m:
                sides[int(m.group(1))] = res[1]
    if sides:
        patch_anim_wad(a.gp4, a.out, sides)
    print('%d of %d tracks written -> %s' % (ok, len(keys), a.out))
    return 0 if ok == len(keys) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
