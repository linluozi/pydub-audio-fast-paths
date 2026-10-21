"""Craft audio whose 1s-window RMS lands right at the -30 dBFS threshold."""
import wave, struct, math, random, sys

THRESH = 0.03162277660168379 * 32768   # db_to_float(-30) * 2**15

def write(path, samples, rate=44100, channels=2):
    data = bytearray()
    for v in samples:
        v = max(-32768, min(32767, int(v)))
        for _ in range(channels):
            data += struct.pack('<h', v)
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(bytes(data))
    print(path, len(data))

# staircase: each 1s block has a constant amplitude, stepping across the
# threshold by +-1 rms unit so the <= comparison is exercised exactly.
rate = 44100
blocks = []
random.seed(4)
targets = []
for k in range(-6, 7):
    targets.append(THRESH + k)
for t in targets:
    # constant-amplitude block -> window rms == amplitude (rounded)
    n = rate
    blocks.extend([t] * n)
# add dither so sqrt() lands between integers too
for t in targets:
    n = rate
    vals = []
    for i in range(n):
        vals.append(t + (1 if (i * 7919) % 13 < 6 else -1))
    blocks.extend(vals)
write('audio_thresh.wav', blocks)

# long file for the >2^53 sum path: 9.5M samples of full-scale 16-bit
n = 9_500_000
write('audio_wide.wav', [32767] * n, channels=1)
