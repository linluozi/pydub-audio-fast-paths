"""
Fetch the pydub 0.25.1 test fixtures that are too large to ship in this repo.

Only the "upstream test suite" stage of verify.py needs these; the differential
probe and the regression tests use the synthesised fixtures from gen_all.py.

The five 192 kHz / 64-bit files alone are 46 MB, which is not reasonable to keep
in git for a fork whose point is a 483-line patch. They are fetched from the
upstream repo at the exact commit this fork is based on, and every file is
checked against the size the API reports.

Usage:
    python harness/fetch_upstream_data.py            # into upstream/test/data
    python harness/fetch_upstream_data.py --check    # report what is missing
"""
import json
import os
import sys
import urllib.request

COMMIT = '103e339d3bc7a9a58a9f1de65f7d8074659b5f5a'
REPO = 'jiaaro/pydub'
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'upstream', 'test', 'data')

# name -> size, as reported by the GitHub contents API at COMMIT
EXPECTED = {
    'bach.ogg': 85644,
    'cover.jpg': 8640,
    'cover.png': 31654,
    'creative_common.mp4': 266745,
    'format_test.m4a': 79534,
    'party.mp3': 52694,
    'tessst.mp3': 12570,
    'test-192khz-16bit.wav': 5344910,
    'test-192khz-24bit.wav': 8017278,
    'test-192khz-32bit.flac': 1752637,
    'test-192khz-32bit.wav': 10689658,
    'test-192khz-64bit.wav': 21379118,
    'test-dc_offset.wav': 882044,
    'test1-24bit.wav': 2650192,
    'test1-8bit.wav': 640684,
    'test1.mp3': 120753,
    'test1.raw': 1281212,
    'test1.wav': 1281256,
    'test1_empty.wav': 44,
    'test2.mp3': 80946,
    'test3.mp3': 66858,
    'test4.wav': 768044,
    'test5.webm': 6873,
    'wrong_extension.aac': 79534,
}

RAW = 'https://raw.githubusercontent.com/%s/%s/test/data/' % (REPO, COMMIT)


def missing():
    out = []
    for name, size in sorted(EXPECTED.items()):
        path = os.path.join(DATA, name)
        if not os.path.isfile(path) or os.path.getsize(path) != size:
            out.append(name)
    return out


def fetch(name, size):
    path = os.path.join(DATA, name)
    url = RAW + name
    sys.stdout.write('  %-28s %9d  ' % (name, size))
    sys.stdout.flush()
    with urllib.request.urlopen(url, timeout=120) as resp:
        blob = resp.read()
    if len(blob) != size:
        raise SystemExit('size mismatch for %s: got %d, expected %d'
                         % (name, len(blob), size))
    with open(path, 'wb') as fh:
        fh.write(blob)
    print('ok')


def main():
    if not os.path.isdir(DATA):
        os.makedirs(DATA)
    todo = missing()
    if '--check' in sys.argv:
        print('%d of %d fixtures missing or wrong size' % (len(todo), len(EXPECTED)))
        for name in todo:
            print('  ' + name)
        return 0 if not todo else 1
    if not todo:
        print('all %d upstream fixtures present' % len(EXPECTED))
        return 0
    print('fetching %d fixture(s) from %s@%s' % (len(todo), REPO, COMMIT[:8]))
    for name in todo:
        fetch(name, EXPECTED[name])
    print('done')
    return 0


if __name__ == '__main__':
    sys.exit(main())
