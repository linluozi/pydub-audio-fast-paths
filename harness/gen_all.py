#!/usr/bin/env python
"""Generate every audio fixture the probes need, into the directory given as argv[1].

All fixtures are synthesised, so the ZIP carries no large binary media.  Each
one exists to make a specific branch observable:

  audio_10s/30s/60s.wav   speech-like bursts + digital silence  (general workload)
  audio_thresh.wav        1 s blocks stepping +-6 rms units across -30 dBFS
                          (exercises the `rms <= threshold` boundary exactly)
  audio_huge.wav          200 s of full-scale samples: a 190 s window sums past
                          2**53, where audioop's double accumulation drifts to
                          32766 while the exact integer path gives 32767
  audio_wide.wav          9.5 M full-scale samples, sums below 2**53
  audio_ramp.wav          loud -> medium -> quiet (compressor attack + release)
  audio_8bit_mono.wav     8-bit unsigned path
  audio_short.wav         1.5 s clip, shorter than the default window
  audio_32bit.wav         32-bit samples (reader takes the audioop branch)
"""
from __future__ import print_function

import math
import os
import random
import struct
import sys
import wave


def write(path, samples, rate=44100, channels=2, width=2):
    code = {1: '<b', 2: '<h', 4: '<i'}[width]
    data = bytearray()
    limit = {1: (-128, 127), 2: (-32768, 32767), 4: (-2 ** 31, 2 ** 31 - 1)}[width]
    for value in samples:
        if value < limit[0]:
            value = limit[0]
        elif value > limit[1]:
            value = limit[1]
        packed = struct.pack(code, int(value))
        for _ in range(channels):
            data += packed
    with wave.open(path, 'wb') as fh:
        fh.setnchannels(channels)
        fh.setsampwidth(width)
        fh.setframerate(rate)
        fh.writeframes(bytes(data))
    print('  %-24s %9d bytes' % (os.path.basename(path), len(data)))


def speech_like(seconds, rate=44100, amp=12000, seed=7):
    rnd = random.Random(seed)
    out = []
    for i in range(int(seconds * rate)):
        t = i / float(rate)
        if (t % 2.0) < 1.4:
            value = int(amp * math.sin(2 * math.pi * 220 * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 3 * t)))
            value += rnd.randint(-300, 300)
        else:
            value = 0
        out.append(value)
    return out


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    for seconds in (10, 30, 60):
        write(os.path.join(out_dir, 'audio_%ds.wav' % seconds), speech_like(seconds))

    rate = 44100
    thresh = 10 ** (-30 / 20.0) * 32768.0
    blocks = []
    for offset in range(-6, 7):
        blocks.extend([thresh + offset] * rate)
    for offset in range(-6, 7):
        blocks.extend([thresh + offset + (1 if (i * 7919) % 13 < 6 else -1) for i in range(rate)])
    write(os.path.join(out_dir, 'audio_thresh.wav'), blocks)

    write(os.path.join(out_dir, 'audio_huge.wav'), [32767] * (200 * rate), channels=1)
    write(os.path.join(out_dir, 'audio_wide.wav'), [32767] * 9500000, channels=1)

    ramp = []
    ramp.extend(int(30000 * math.sin(2 * math.pi * 200 * i / rate)) for i in range(rate))
    ramp.extend(int(4000 * math.sin(2 * math.pi * 200 * i / rate)) for i in range(int(1.5 * rate)))
    ramp.extend(int(30 * math.sin(2 * math.pi * 200 * i / rate)) for i in range(int(0.5 * rate)))
    write(os.path.join(out_dir, 'audio_ramp.wav'), ramp)

    rate8 = 8000
    vals = [int(90 * math.sin(2 * math.pi * 300 * i / rate8)) if (i // 800) % 2 else 0
            for i in range(rate8 * 3)]
    write(os.path.join(out_dir, 'audio_8bit_mono.wav'), vals, rate=rate8, channels=1, width=1)

    write(os.path.join(out_dir, 'audio_short.wav'),
          [int(8000 * math.sin(2 * math.pi * 200 * i / rate8)) for i in range(12000)],
          rate=rate8)

    vals32 = []
    for i in range(rate * 3):
        amp = 200000000 if (i // rate) % 2 == 0 else 5000000
        vals32.append(int(amp * math.sin(2 * math.pi * 180 * i / rate)))
    write(os.path.join(out_dir, 'audio_32bit.wav'), vals32, width=4)

    # 24-bit inputs: pydub widens 24 -> 32 bit on load.  Include every
    # sign-extension case (top byte < 0x80 and >= 0x80) plus a long tail.
    frames = bytearray()
    # every sign-extension case, repeated enough to be measurable
    for _ in range(400):
        for b0 in range(0, 256, 17):
            for b1 in range(0, 256, 51):
                for b2 in (0x00, 0x7F, 0x80, 0xFF):
                    frames += bytes(bytearray((b0, b1, b2)))
    with wave.open(os.path.join(out_dir, 'audio_24bit.wav'), 'wb') as fh:
        fh.setnchannels(1)
        fh.setsampwidth(3)
        fh.setframerate(8000)
        fh.writeframes(bytes(frames))
    print('  %-24s %9d bytes' % ('audio_24bit.wav', len(frames)))

    big = bytearray()
    for i in range(400000):
        big += struct.pack('<i', (i * 2654435761) % (2 ** 31))[:3]
    with wave.open(os.path.join(out_dir, 'audio_24bit_big.wav'), 'wb') as fh:
        fh.setnchannels(2)
        fh.setsampwidth(3)
        fh.setframerate(44100)
        fh.writeframes(bytes(big))
    print('  %-24s %9d bytes' % ('audio_24bit_big.wav', len(big)))

    print('fixtures written to %s' % os.path.abspath(out_dir))


if __name__ == '__main__':
    main()
