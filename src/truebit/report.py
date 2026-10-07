# Runs every check on one file and builds the report (the same JSON shape as the
# audio-quality reports in context/Sources). Can also draw a spectrogram picture.

import json
import subprocess
from pathlib import Path

from truebit.loudness import analyze_loudness
from truebit.probe import check_ffmpeg, decode, probe
from truebit.spectrum import analyze_spectrum
from truebit.verdict import make_verdict

AUDIO_EXTENSIONS = {".flac", ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".alac", ".aiff",
                    ".aif", ".wma"}


# The full report for one audio file
def analyze_file(file_path):
    check_ffmpeg()
    file_info = probe(file_path)
    samples = decode(file_path)
    spectrum = analyze_spectrum(samples, file_info["sample_rate_hz"])
    loudness = analyze_loudness(file_path, samples, file_info["sample_rate_hz"])
    verdict_key, headline, detail = make_verdict(file_info, spectrum)

    return {
        "verdict": verdict_key,
        "verdict_headline": headline,
        "verdict_detail": detail,
        "file": file_info,
        "loudness": loudness,
        "spectrum": spectrum,
    }


# Saves the report next to the audio file as song.truebit.json
def save_report(report, file_path):
    output_path = Path(file_path).with_suffix(".truebit.json")
    output_path.write_text(json.dumps(report, indent=4), encoding="utf-8")
    return output_path


# Draws a spectrogram picture (time across, frequency up) with FFmpeg's showspectrumpic
def save_spectrogram(file_path):
    output_path = Path(file_path).with_suffix(".spectrogram.png")
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(file_path),
               "-lavfi", "showspectrumpic=s=1280x640:legend=1", str(output_path)]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        return None
    return output_path


# Every audio file in a folder (and its sub-folders)
def find_audio_files(folder):
    found = []
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            found.append(path)
    return found
