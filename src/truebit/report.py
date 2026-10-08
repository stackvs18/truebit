# Runs every check on one file and builds the report (the same JSON shape as the
# audio-quality reports in context/Sources). Can also draw a spectrogram picture.

import json
import subprocess
from pathlib import Path

from truebit.loudness import analyze_loudness
from truebit.probe import check_ffmpeg, decode, probe, to_mono
from truebit.spectrum import analyze_spectrum
from truebit.verdict import make_verdict

AUDIO_EXTENSIONS = {".flac", ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".alac", ".aiff",
                    ".aif", ".wma"}


# The full report for one audio file
def analyze_file(file_path):
    check_ffmpeg()
    file_info = probe(file_path)
    channel_count = file_info["channels"]

    # Every channel, for honest peak and clipping numbers; a mono average for the spectrum
    all_samples = decode(file_path)
    mono_samples = to_mono(all_samples, channel_count)

    spectrum = analyze_spectrum(mono_samples, file_info["sample_rate_hz"])
    loudness = analyze_loudness(file_path, all_samples, file_info["sample_rate_hz"], channel_count)
    verdict_key, headline, detail = make_verdict(file_info, spectrum)

    return {
        "verdict": verdict_key,
        "verdict_headline": headline,
        "verdict_detail": detail,
        "file": file_info,
        "loudness": loudness,
        "spectrum": spectrum,
    }


# Where saved reports go: a "truebit-reports" folder in the current folder.
# (Never next to the music, so a music library is never cluttered or changed.)
def reports_folder():
    folder = Path.cwd() / "truebit-reports"
    folder.mkdir(exist_ok=True)
    return folder


# Saves the report as truebit-reports/song.truebit.json
def save_report(report, file_path, folder=None):
    if folder is None:
        folder = reports_folder()
    output_path = Path(folder) / (Path(file_path).stem + ".truebit.json")
    output_path.write_text(json.dumps(report, indent=4, ensure_ascii=False), encoding="utf-8")
    return output_path


# Draws a spectrogram picture (time across, frequency up) with FFmpeg's showspectrumpic,
# saved as truebit-reports/song.spectrogram.png
def save_spectrogram(file_path, folder=None):
    if folder is None:
        folder = reports_folder()
    output_path = Path(folder) / (Path(file_path).stem + ".spectrogram.png")
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
