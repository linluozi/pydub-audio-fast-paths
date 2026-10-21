import wave, struct, math
rate = 8000
vals = [int(90 * math.sin(2*math.pi*300*i/rate)) if (i//800) % 2 else 0 for i in range(8000*3)]
data = bytearray()
for v in vals:
    data += struct.pack('<b', max(-128, min(127, v)))
with wave.open('audio_8bit_mono.wav','wb') as w:
    w.setnchannels(1); w.setsampwidth(1); w.setframerate(rate); w.writeframes(bytes(data))
print('8bit mono', len(data))
vals2 = [int(8000*math.sin(2*math.pi*200*i/rate)) for i in range(12000)]
d2 = bytearray()
for v in vals2:
    for _ in range(2):
        d2 += struct.pack('<h', v)
with wave.open('audio_short.wav','wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(d2))
print('short', len(d2), 'ms', 12000*1000//rate)
