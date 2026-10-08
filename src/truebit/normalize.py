# `truebit normalize`: make a track exactly as loud as streaming services play it.
#
# Uses FFmpeg's loudnorm filter (EBU R128) in two passes:
#   pass 1: measure the track's loudness, loudness range and true peak
#   pass 2: apply one precise gain change using those measurements ("linear" mode keeps the
#           dynamics exactly as they were, instead of squashing them)
#
# Targets (integrated loudness):
#   spotify / youtube  -14 LUFS     apple   -16 LUFS     broadcast (EBU R128)  -23 LUFS

import json
import subprocess

from truebit.formats import encoder_options, output_extension, output_sample_rate, standard_bitrate_at_least
from truebit.loudness import ebu_r128
from truebit.output import output_path_for, run_filter
from truebit.probe import AudioError, check_ffmpeg, probe

PRESETS = {"spotify": -14.0, "youtube": -14.0, "apple": -16.0, "broadcast": -23.0}
TRUE_PEAK_LIMIT = -1.0  # dBTP: leave 1 dB of headroom so encoders don't clip


# Keeps a number inside a range, e.g. keep_between(0.78, -99, 0) -> 0
def keep_between(value, lowest, highest):
    if value < lowest:
        return lowest
    if value > highest:
        return highest
    return value


# Pass 1: loudnorm measures the track and prints JSON at the end of its output
def measure_for_loudnorm(input_path, target_lufs):
    filter_text = f"loudnorm=I={target_lufs}:TP={TRUE_PEAK_LIMIT}:LRA=11:print_format=json"
    command = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(input_path),
               "-af", filter_text, "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    json_start = result.stderr.rfind("{")
    json_end = result.stderr.rfind("}")
    if json_start == -1 or json_end == -1:
        raise AudioError("Couldn't measure loudness: " + result.stderr.strip()[-300:])
    return json.loads(result.stderr[json_start: json_end + 1])


# Measures a file and builds the loudnorm filter that moves it to the target.
# Returns (filter text, the measurements).
def loudnorm_filter_for(input_path, target_lufs):
    # Step 1: measure
    measured = measure_for_loudnorm(input_path, target_lufs)
    if measured["input_i"] in ("-inf", "inf"):
        raise AudioError("The file is silent, there's nothing to normalize.")

    # Step 2: build one exact gain change from the measurements.
    # loudnorm only accepts values in certain ranges; very loud masters can measure above
    # 0 LUFS (we found one at +0.78), so each value is kept inside its allowed range.
    measured_i = keep_between(float(measured["input_i"]), -99, 0)
    measured_tp = keep_between(float(measured["input_tp"]), -99, 99)
    measured_lra = keep_between(float(measured["input_lra"]), 0, 99)
    measured_thresh = keep_between(float(measured["input_thresh"]), -99, 0)
    offset = keep_between(float(measured["target_offset"]), -99, 99)
    filter_text = (
        f"loudnorm=I={target_lufs}:TP={TRUE_PEAK_LIMIT}:LRA=11"
        f":measured_I={measured_i}:measured_TP={measured_tp}"
        f":measured_LRA={measured_lra}:measured_thresh={measured_thresh}"
        f":offset={offset}:linear=true"
    )
    return filter_text, measured


# Normalizes a file. Returns (output path, before numbers, after numbers).
# The result keeps the original's format (MP3 stays MP3) unless output_format is given.
def normalize_file(input_path, target_lufs=-14.0, output=None, output_format=None):
    check_ffmpeg()
    file_info = probe(input_path)

    # Step 1 and 2: measure, then apply one exact gain change
    filter_text, measured = loudnorm_filter_for(input_path, target_lufs)
    extension = output_extension(input_path, file_info["codec"], output_format)
    output_path = output_path_for(input_path, f"normalized{int(target_lufs)}", output, extension)
    encoder_args = encoder_options(extension, file_info, standard_bitrate_at_least(file_info["bitrate_kbps"]))
    sample_rate = output_sample_rate(extension, file_info["sample_rate_hz"])
    run_filter(input_path, output_path, filter_text, sample_rate, encoder_args)

    # Step 3: check the result
    after_lufs, after_range, after_peak = ebu_r128(output_path)
    before = {"integrated_lufs": float(measured["input_i"]), "true_peak_dbtp": float(measured["input_tp"])}
    after = {"integrated_lufs": after_lufs, "true_peak_dbtp": after_peak}
    return output_path, before, after
