"""Craft audio whose 1 s window sum exceeds 2**53, to exercise the audioop fallback.

2**53 / (32767**2) = 8,389,121 samples, i.e. a 190 s mono window at 44.1 kHz.
"""
import wave, struct
rate = 44100
n = 200 * rate              # 200 s, one channel -> 8.82 M samples
data = bytearray()
for _ in range(n):
    data += struct.pack('<h', 32767)
with wave.open('audio_huge.wav', 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(bytes(data))
print('audio_huge.wav', len(data), 'samples', n, 'sumsq', n*32767*32767, '>2^53', n*32767*32767 > 2**53)
