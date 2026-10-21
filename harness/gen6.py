"""32-bit stereo WAV: quiet/loud alternating, so the reader's 4-byte branch runs."""
import wave, struct, math
rate = 44100
vals = []
for i in range(rate * 3):
    block = i // rate
    amp = 200000000 if block % 2 == 0 else 5000000
    vals.append(int(amp * math.sin(2 * math.pi * 180 * i / rate)))
data = bytearray()
for v in vals:
    for _ in range(2):
        data += struct.pack('<i', v)
with wave.open('audio_32bit.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(4); w.setframerate(rate)
    w.writeframes(bytes(data))
print('audio_32bit.wav', len(data))
