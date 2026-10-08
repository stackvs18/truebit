# Reads a file's details (codec, bitrate, sample rate, tags...) with ffprobe, and decodes its
# audio into numbers with ffmpeg. Both tools come with FFmpeg.

import json
import os
import shutil
import subprocess

import numpy as np

from truebit.formats import LOSSY_CODECS

# The tags we show (they're called the same in MP3, FLAC, M4A and OGG files)
TAG_NAMES = ["title", "artist", "album", "date", "genre"]


class AudioError(Exception):
    pass


# Stops early with a clear message if FFmpeg isn't installed
def check_ffmpeg():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AudioError("FFmpeg is not installed. On Windows: winget install Gyan.FFmpeg")


# For MP3s: reads the start of the file to find the encoder (e.g. "LAME3.100") and whether the
# bitrate is constant (CBR) or variable (VBR). The LAME encoder writes an "Xing" header in VBR
# files and an "Info" header in CBR files; Fraunhofer encoders write "VBRI" for VBR.
def read_mp3_header(file_path):
    with open(file_path, "rb") as audio_file:
        # Step 1: skip the ID3 tag at the start (title, artist, cover art), if there is one.
        # Its size is stored in 4 bytes of 7 bits each.
        first_bytes = audio_file.read(10)
        offset = 0
        if first_bytes[:3] == b"ID3" and len(first_bytes) == 10:
            tag_size = 0
            for byte in first_bytes[6:10]:
                tag_size = tag_size * 128 + (byte & 0x7F)
            offset = 10 + tag_size

        # Step 2: the first audio frame, where those headers live
        audio_file.seek(offset)
        frame_bytes = audio_file.read(4096)

    # Step 3: look for the markers
    if b"Xing" in frame_bytes or b"VBRI" in frame_bytes:
        mode = "VBR"
    else:
        mode = "CBR"
    # The encoder's name is followed by its version, e.g. "LAME3.100" or "Lavc63.1.102"
    encoder = None
    for marker in [b"LAME", b"Lavc"]:
        position = frame_bytes.find(marker)
        if position != -1:
            encoder = marker.decode()
            for byte in frame_bytes[position + 4: position + 16]:
                character = chr(byte)
                if not (character.isdigit() or character == "."):
                    break
                encoder = encoder + character
            encoder = encoder.rstrip(".")
            break
    return mode, encoder


# The tags (title, artist...) and the encoder tag, from the stream and the container
def read_tags(data, audio_stream):
    # Step 1: collect every tag, with lowercase names (FLAC writes TITLE, MP3 writes title)
    all_tags = {}
    sources = [audio_stream.get("tags", {}), data.get("format", {}).get("tags", {})]
    for source in sources:
        for name, value in source.items():
            all_tags[name.lower()] = value

    # Step 2: keep the ones we show
    tags = {}
    for name in TAG_NAMES:
        if all_tags.get(name):
            tags[name] = all_tags[name]
    encoder = all_tags.get("encoder") or all_tags.get("encoded_by")
    return tags, encoder


# True if the file has a cover picture inside
def has_cover_art(data):
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and stream.get("disposition", {}).get("attached_pic") == 1:
            return True
    return False


# File details as a dict, in the shape of the "file" part of the report
def probe(file_path):
    command = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
               str(file_path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AudioError("Can't read this file: " + result.stderr.strip()[:200])

    data = json.loads(result.stdout)

    # Step 1: find the first audio stream
    audio_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            audio_stream = stream
            break
    if audio_stream is None:
        raise AudioError("This file has no audio.")

    file_format = data.get("format", {})
    codec = audio_stream.get("codec_name", "unknown")
    is_lossy = codec in LOSSY_CODECS

    # Step 2: the bitrate the file's properties say (what a music player shows):
    # from the audio stream if it says, otherwise from the whole file
    bitrate = audio_stream.get("bit_rate") or file_format.get("bit_rate")
    bitrate_kbps = round(int(bitrate) / 1000) if bitrate else None

    # Step 3: the bitrate really stored: the file's size divided by its length
    duration = float(file_format.get("duration", 0) or 0)
    file_size = os.path.getsize(file_path)
    data_rate_kbps = round(file_size * 8 / duration / 1000) if duration > 0 else None

    # Step 4: bit depth only makes sense for lossless formats
    bit_depth = audio_stream.get("bits_per_raw_sample") or audio_stream.get("bits_per_sample")
    bit_depth = int(bit_depth) if bit_depth and int(bit_depth) > 0 else None

    # Step 5: tags, cover art, the encoder and (for MP3) constant or variable bitrate
    tags, encoder = read_tags(data, audio_stream)
    bitrate_mode = None
    if codec in ("mp3", "mp3float"):
        bitrate_mode, mp3_encoder = read_mp3_header(file_path)
        if mp3_encoder:
            encoder = mp3_encoder

    container = file_format.get("format_name", "unknown").split(",")[0]
    return {
        "container": container,
        "container_name": file_format.get("format_long_name", container),
        "codec": codec,
        "codec_name": audio_stream.get("codec_long_name", codec),
        "lossy_codec": is_lossy,
        "bitrate_kbps": bitrate_kbps,
        "data_rate_kbps": data_rate_kbps,
        "bitrate_mode": bitrate_mode,
        "sample_rate_hz": int(audio_stream.get("sample_rate", 44100)),
        "bit_depth": None if is_lossy else bit_depth,
        "channels": int(audio_stream.get("channels", 2)),
        "channel_layout": audio_stream.get("channel_layout"),
        "duration_seconds": duration,
        "file_size_bytes": file_size,
        "encoder": encoder,
        "tags": tags,
        "has_cover_art": has_cover_art(data),
    }


# Decodes the audio into a numpy array of samples between -1.0 and 1.0 (original sample rate).
# Only the first max_seconds are used, which is plenty to find the cutoff and keeps it fast.
#
# Returns the samples of EVERY channel, interleaved (left, right, left, right...).
# We don't let FFmpeg mix stereo down to mono: its downmix adds the channels together,
# which can push values above 1.0 and make a clean file look clipped.
def decode(file_path, max_seconds=120):
    command = ["ffmpeg", "-v", "error", "-i", str(file_path), "-t", str(max_seconds),
               "-map", "0:a:0", "-f", "f32le", "-"]
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
