"""Audio for the compressor's release branch: loud -> moderately loud -> quiet."""
import wave, struct, math

rate = 44100
vals = []
# 1.0s loud (near full scale)
for i in range(rate):
    vals.append(int(30000 * math.sin(2 * math.pi * 200 * i / rate)))
# 1.5s moderately loud: still above -20 dBFS threshold but well below the peak
for i in range(int(1.5 * rate)):
    vals.append(int(4000 * math.sin(2 * math.pi * 200 * i / rate)))
# 0.5s quiet
for i in range(int(0.5 * rate)):
    vals.append(int(30 * math.sin(2 * math.pi * 200 * i / rate)))
data = bytearray()
for v in vals:
    for _ in range(2):
        data += struct.pack('<h', v)
with wave.open('audio_ramp.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(bytes(data))
print('audio_ramp.wav', len(data), 'samples/ch', len(vals))
