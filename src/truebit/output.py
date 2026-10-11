# Shared helpers for commands that write a new audio file (repair, normalize, fix).

import subprocess
from pathlib import Path

from truebit.formats import COVER_ART_EXTENSIONS
from truebit.probe import AudioError


# Picks where to save the result: "song.mp3" -> "song.repaired.mp3".
# The extension is the original's unless another one is given (see formats.output_extension).
def output_path_for(input_path, label, chosen_output=None, extension=None):
    if chosen_output is not None:
        return Path(chosen_output)
    input_path = Path(input_path)
    if extension is None:
        extension = input_path.suffix.lower()
    return input_path.with_name(input_path.stem + "." + label + extension)


# Runs FFmpeg: reads input_path, applies the filter chain and writes output_path with the
# given encoder options. Keeps the tags (title, artist, album...) and, where the format
# allows it, the cover art. tags_from = another file to copy those from (used when the
# input is a temporary file).
def run_filter(input_path, output_path, filter_chain, sample_rate, encoder_args, tags_from=None):
    extension = Path(output_path).suffix.lower()

    # Step 1: the inputs (the audio, and maybe a second file that has the tags)
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(input_path)]
    tags_input = "0"
    if tags_from is not None:
        command = command + ["-i", str(tags_from)]
        tags_input = "1"

    # Step 2: what goes into the new file: the audio, the tags, and the cover art if any
    command = command + ["-map", "0:a:0", "-map_metadata", tags_input]
    if extension in COVER_ART_EXTENSIONS:
        command = command + ["-map", tags_input + ":v?", "-c:v", "copy", "-disposition:v", "attached_pic"]

    # Step 3: the filters and the encoder
    command = command + ["-af", filter_chain, "-ar", str(sample_rate)] + encoder_args + [str(output_path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AudioError("FFmpeg failed: " + result.stderr.strip()[:300])
    return Path(output_path)
