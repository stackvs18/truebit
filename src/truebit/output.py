# Shared helpers for commands that write a new audio file (repair, normalize).

import subprocess
from pathlib import Path

from truebit.probe import AudioError

LOSSLESS_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif", ".alac"}


# Picks where to save the result: "song.flac" -> "song.repaired.flac".
# Lossy inputs (MP3, AAC...) are saved as FLAC, so the fix itself adds no new quality loss.
def output_path_for(input_path, label, chosen_output=None):
    if chosen_output is not None:
        return Path(chosen_output)
    input_path = Path(input_path)
    extension = input_path.suffix.lower()
    if extension not in LOSSLESS_EXTENSIONS:
        extension = ".flac"
    return input_path.with_name(input_path.stem + "." + label + extension)


# Runs FFmpeg with an audio filter chain, keeping the original sample rate
def run_filter(input_path, output_path, filter_chain, sample_rate):
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(input_path),
               "-af", filter_chain, "-ar", str(sample_rate), str(output_path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AudioError("FFmpeg failed: " + result.stderr.strip()[:300])
    return Path(output_path)
