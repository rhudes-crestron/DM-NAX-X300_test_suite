#!/usr/bin/env python3
"""Generate stereo sine-wave WAV files for streaming tests.

Each file is 2 minutes of a single frequency at -20 dBFS, 48 kHz, 16-bit stereo.
Files are created only if they don't already exist.
"""
import math
import os
import struct
import wave

SAMPLE_RATE = 48000
DURATION_S = 900        # 15 minutes — must outlast the full streaming test session
AMPLITUDE = 0.1         # ≈ -20 dBFS
BIT_DEPTH = 16
CHANNELS = 2

# Frequencies matching the spreadsheet StreamRoutings sheet
TONE_FREQUENCIES = [100, 200, 400, 800, 1000, 1500, 3000, 6000, 12000]


def tone_filename(freq_hz):
    min_s = DURATION_S // 60
    return f"{freq_hz}Hz_-20dBFS_{min_s}min.wav"


def generate_tone(out_dir, freq_hz, force=False):
    """Generate a stereo sine-wave WAV file.

    Returns the full path to the file.
    """
    path = os.path.join(out_dir, tone_filename(freq_hz))
    if os.path.exists(path) and not force:
        return path

    n_frames = SAMPLE_RATE * DURATION_S
    max_val = (2 ** (BIT_DEPTH - 1)) - 1
    chunk = SAMPLE_RATE  # write 1 second at a time

    with wave.open(path, "w") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(BIT_DEPTH // 8)
        wf.setframerate(SAMPLE_RATE)

        for start in range(0, n_frames, chunk):
            end = min(start + chunk, n_frames)
            frames = bytearray()
            for i in range(start, end):
                t = i / SAMPLE_RATE
                val = int(AMPLITUDE * max_val * math.sin(2 * math.pi * freq_hz * t))
                frames += struct.pack("<hh", val, val)
            wf.writeframes(bytes(frames))

    return path


def generate_all(out_dir, force=False):
    """Generate all tone files. Returns dict {freq: path}."""
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for freq in TONE_FREQUENCIES:
        path = generate_tone(out_dir, freq, force=force)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  {freq:>5d} Hz → {os.path.basename(path)}  ({size_mb:.1f} MB)")
        result[freq] = path
    return result


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audiofiles"
    )
    print(f"Generating test tones in {out}")
    generate_all(out)
    print("Done.")
