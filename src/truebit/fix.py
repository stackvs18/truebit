# `truebit fix`: one command for problem files. For each file it:
#
#   1. checks it (the same analysis as `truebit check`)
#   2. repairs it if needed: rebuilds clipped peaks, turns down background hiss
#   3. makes fakes honest: a "FLAC" that really holds a 128 kbps MP3 becomes a 160 kbps MP3,
#      and a "320 kbps" MP3 that's really 128 kbps becomes a 160 kbps MP3. The sound stays the
#      same (nothing can bring back what the first encoder deleted), but the file gets much
#      smaller and its label finally tells the truth.
#   4. normalizes the loudness (-14 LUFS by default, like Spotify)
#
# Results go into ./truebit-fixed/, so the originals are never changed.

import tempfile
from pathlib import Path

from truebit.formats import (
    encoder_options,
    honest_bitrate,
    output_extension,
    output_sample_rate,
    standard_bitrate_at_least,
)
from truebit.normalize import loudnorm_filter_for
from truebit.output import run_filter
from truebit.probe import check_ffmpeg
from truebit.repair import DEFAULT_NOISE_FLOOR_DB, MUSIC_NOT_HISS_DB, build_filter_chain
from truebit.report import analyze_file
from truebit.verdict import likely_source

# A noise floor between these two levels is background hiss (quieter = silence, louder = music)
HISS_LEVEL_DB = -60
# Clipping on fewer than 1 sample in 1,000 can't be heard, and rebuilding peaks is slow
# (about a minute per song), so below that we leave the peaks alone
AUDIBLE_CLIPPING_SHARE = 0.001
ANALYSED_SECONDS = 120  # check and scan look at the first 2 minutes


# Decides what a file needs, from its report. Returns a dict of yes/no steps and the reasons.
def plan_fix(report):
    loudness = report["loudness"]
    file_info = report["file"]
    plan = {"declip": False, "denoise": False, "honest_bitrate": None, "problems": []}

    # Step 1: clipping (the tops of the waves cut off), as a share of the samples checked
    clipped = loudness["clipped_samples"]
    seconds_checked = min(file_info["duration_seconds"], ANALYSED_SECONDS)
    samples_checked = file_info["sample_rate_hz"] * seconds_checked * file_info["channels"]
    if samples_checked > 0 and clipped / samples_checked >= AUDIBLE_CLIPPING_SHARE:
        plan["declip"] = True
        plan["problems"].append(f"{clipped:,} clipped samples")

    # Step 2: steady background hiss
    noise_floor = loudness["noise_floor_dbfs"]
    if noise_floor is not None and HISS_LEVEL_DB < noise_floor < MUSIC_NOT_HISS_DB:
        plan["denoise"] = True
        plan["problems"].append(f"background noise at {noise_floor:g} dB")

    # Step 3: fake files get an honest bitrate that matches the sound they really hold
    if report["verdict"] in ("fake_lossless", "fake_bitrate"):
        real_kbps = likely_source(report["spectrum"]["cutoff_hz"])[1]  # e.g. 128
        plan["honest_bitrate"] = honest_bitrate(real_kbps)
        plan["problems"].append(report["verdict_headline"])
    return plan


# Picks the format and bitrate to save as. Fake "lossless" files become MP3s, because there's
# no lossless sound in them to keep; everything else stays in its own format.
def choose_output(input_path, report, plan, chosen_format):
    file_info = report["file"]
    if chosen_format is None and report["verdict"] == "fake_lossless":
        extension = ".mp3"
    else:
        extension = output_extension(input_path, file_info["codec"], chosen_format)

    if plan["honest_bitrate"] is not None:
        bitrate = plan["honest_bitrate"]
    else:
        bitrate = standard_bitrate_at_least(file_info["bitrate_kbps"])
    return extension, bitrate


# Fixes one file into output_folder. Returns a dict with the before and after reports.
def fix_file(input_path, output_folder, target_lufs=-14.0, strength="light", chosen_format=None,
             used_paths=None):
    check_ffmpeg()
    input_path = Path(input_path)

    # Step 1: check the file and decide what it needs
    before = analyze_file(input_path)
    plan = plan_fix(before)
    extension, bitrate = choose_output(input_path, before, plan, chosen_format)

    # Step 2: pick a name in the output folder that this run hasn't used yet
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    output_path = Path(output_folder) / (input_path.stem + extension)
    number = 2
    while used_paths is not None and output_path in used_paths:
        output_path = Path(output_folder) / f"{input_path.stem} ({number}){extension}"
        number = number + 1
    if used_paths is not None:
        used_paths.add(output_path)

    file_info = before["file"]
    with tempfile.TemporaryDirectory(prefix="truebit-fix-") as work_folder:
        source = input_path

        # Step 3: repair into a temporary lossless file, so the repair adds no extra loss
        if plan["declip"] or plan["denoise"]:
            noise_floor = before["loudness"]["noise_floor_dbfs"]
            if noise_floor is None or noise_floor > MUSIC_NOT_HISS_DB:
                noise_floor = DEFAULT_NOISE_FLOOR_DB
            chain = build_filter_chain(declick=False, declip=plan["declip"], denoise=plan["denoise"],
                                       strength=strength, noise_floor_db=noise_floor)
            repaired_path = Path(work_folder) / "repaired.wav"
            run_filter(source, repaired_path, chain, file_info["sample_rate_hz"], ["-c:a", "pcm_f32le"])
            source = repaired_path

        # Step 4: normalize the loudness and write the final file in one go, copying the
        # tags and cover art from the original
        loudnorm_filter = loudnorm_filter_for(source, target_lufs)[0]
        sample_rate = output_sample_rate(extension, file_info["sample_rate_hz"])
        run_filter(source, output_path, loudnorm_filter, sample_rate,
                   encoder_options(extension, file_info, bitrate), tags_from=input_path)

    # Step 5: check the result
    after = analyze_file(output_path)
    return {"input": input_path, "output": output_path, "plan": plan, "before": before, "after": after}


# Fixes every file in a list. Files that fail are reported, not fatal.
def fix_many(file_list, output_folder, target_lufs=-14.0, strength="light", chosen_format=None):
    results = []
    used_paths = set()
    for file_path in file_list:
        try:
            results.append(fix_file(file_path, output_folder, target_lufs, strength, chosen_format, used_paths))
        except Exception as error:  # one broken file shouldn't stop a whole folder
            results.append({"input": Path(file_path), "error": str(error)})
    return results
