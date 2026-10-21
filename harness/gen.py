import wave, struct, math, random, sys

def gen(path, seconds, rate=44100, channels=2, width=2, seed=7):
    rnd = random.Random(seed)
    n = int(seconds * rate)
    frames = bytearray()
    amp = 12000
    for i in range(n):
        # mostly "speech-like" tone with silent gaps every ~2s
        t = i / rate
        phase = t % 2.0
        v = 0
        if phase < 1.4:
            v = int(amp * math.sin(2 * math.pi * 220 * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 3 * t)))
            v += rnd.randint(-300, 300)
        for _ in range(channels):
            frames += struct.pack('<h', max(-32768, min(32767, v)))
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels); w.setsampwidth(width); w.setframerate(rate)
        w.writeframes(bytes(frames))
    print(path, len(frames), 'bytes')

if __name__ == '__main__':
    for s in (10, 30, 60, 120):
        gen(f'audio_{s}s.wav', s)
