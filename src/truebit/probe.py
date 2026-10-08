# Reads a file's details (codec, bitrate, sample rate...) with ffprobe, and decodes its audio
# into numbers with ffmpeg. Both tools come with FFmpeg.

import json
import shutil
import subprocess

import numpy as np

# Codecs that throw sound away when they compress (lossy)
LOSSY_CODECS = {"mp3", "aac", "vorbis", "opus", "wmav2", "wmav1", "ac3", "eac3", "mp2"}


class AudioError(Exception):
    pass


# Stops early with a clear message if FFmpeg isn't installed
def check_ffmpeg():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AudioError("FFmpeg is not installed. On Windows: winget install Gyan.FFmpeg")


# File details as a dict, in the shape of the "file" part of the report
def probe(file_path):
    command = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
               str(file_path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AudioError("Can't read this file: " + result.stderr.strip()[:200])

    data = json.loads(result.stdout)

    # Find the first audio stream
    audio_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            audio_stream = stream
            break
    if audio_stream is None:
        raise AudioError("This file has no audio.")

    file_format = data.get("format", {})
    codec = audio_stream.get("codec_name", "unknown")

    # Bitrate: from the stream if it says, otherwise from the whole file
    bitrate = audio_stream.get("bit_rate") or file_format.get("bit_rate")
    bitrate_kbps = round(int(bitrate) / 1000) if bitrate else None

    # Bit depth only makes sense for lossless formats
    bit_depth = audio_stream.get("bits_per_raw_sample") or audio_stream.get("bits_per_sample")
    bit_depth = int(bit_depth) if bit_depth and int(bit_depth) > 0 else None

    container = file_format.get("format_name", "unknown").split(",")[0]
    return {
        "container": container,
        "codec": codec,
        "lossy_codec": codec in LOSSY_CODECS,
        "bitrate_kbps": bitrate_kbps,
        "sample_rate_hz": int(audio_stream.get("sample_rate", 44100)),
        "bit_depth": None if codec in LOSSY_CODECS else bit_depth,
        "channels": int(audio_stream.get("channels", 2)),
        "duration_seconds": float(file_format.get("duration", 0) or 0),
    }


# Decodes the audio into a numpy array of samples between -1.0 and 1.0 (mono, original sample rate).
# Only the first max_seconds are used, which is plenty to find the cutoff and keeps it fast.
#
# Returns the samples of EVERY channel, interleaved (left, right, left, right...).
# We don't let FFmpeg mix stereo down to mono: its downmix adds the channels together,
# which can push values above 1.0 and make a clean file look clipped.
def decode(file_path, max_seconds=120):
    command = ["ffmpeg", "-v", "error", "-i", str(file_path), "-t", str(max_seconds),
               "-f", "f32le", "-"]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        raise AudioError("Can't decode this file: " + result.stderr.decode(errors="replace")[:200])
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if len(samples) == 0:
        raise AudioError("The file decoded to silence (no samples).")
    return samples


# Mixes interleaved channels into one mono signal by AVERAGING them (never above 1.0)
def to_mono(samples, channel_count):
    if channel_count <= 1:
        return samples
    usable_length = len(samples) - len(samples) % channel_count
    frames = samples[:usable_length].reshape(-1, channel_count)
    return frames.mean(axis=1)
