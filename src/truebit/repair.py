# `truebit repair`: real audio recovery with FFmpeg's restoration filters.
#
#   declick  (adeclick)  finds short spikes (vinyl crackle, digital pops) and fills them in
#                        from the surrounding sound
#   declip   (adeclip)   finds samples stuck at full volume ("clipping") and rebuilds the
#                        missing tops of the waves
#   denoise  (afftdn)    turns down the steady background hiss in the frequency domain.
#                        We measure the file's noise floor first and tell the filter where
#                        the hiss sits, so it removes noise and not music.
#   limiter  (alimiter)  a safety net at the end, so the repaired peaks don't clip again
#
# What it can NOT do: bring back frequencies an MP3 encoder deleted. That information is gone.

from truebit.formats import encoder_options, output_extension, output_sample_rate, standard_bitrate_at_least
from truebit.loudness import analyze_loudness
from truebit.output import output_path_for, run_filter
from truebit.probe import check_ffmpeg, decode, probe

# How hard the noise reduction works (decibels of reduction)
NOISE_REDUCTION_DB = {"light": 6, "medium": 12, "strong": 20}

# A measured "noise floor" louder than this is quiet music, not hiss
MUSIC_NOT_HISS_DB = -30
DEFAULT_NOISE_FLOOR_DB = -50


# Builds the FFmpeg filter chain for the chosen steps.
# noise_floor_db is the measured hiss level (afftdn accepts -80 to -20 dB).
def build_filter_chain(declick=True, declip=True, denoise=True, strength="medium", noise_floor_db=-50):
    noise_floor_db = max(-80, min(-20, round(noise_floor_db)))
    filters = []
    if declick:
        filters.append("adeclick")
    if declip:
        filters.append("adeclip")
    if denoise:
        filters.append(f"afftdn=nr={NOISE_REDUCTION_DB[strength]}:nf={noise_floor_db}")
    filters.append("alimiter=limit=0.95:level=disabled")
    return ",".join(filters)


# The numbers we compare before and after (measured on every channel, not a mono mix)
def measure(file_path, sample_rate, channel_count):
    samples = decode(file_path)
    loudness = analyze_loudness(file_path, samples, sample_rate, channel_count)
    noise_floor = loudness["noise_floor_dbfs"]
    return {
        "clipped_samples": loudness["clipped_samples"],
        "noise_floor_dbfs": float(noise_floor) if noise_floor is not None else None,
        "true_peak_dbtp": loudness["true_peak_dbtp"],
        "integrated_lufs": loudness["integrated_lufs"],
    }


# Repairs a file and returns (output path, before numbers, after numbers).
# The result keeps the original's format (MP3 stays MP3) unless output_format is given.
def repair_file(input_path, output=None, declick=True, declip=True, denoise=True, strength="medium",
                output_format=None):
    check_ffmpeg()
    if strength not in NOISE_REDUCTION_DB:
        raise ValueError("strength must be light, medium or strong")

    # Step 1: measure the original
    file_info = probe(input_path)
    sample_rate = file_info["sample_rate_hz"]
    channel_count = file_info["channels"]
    before = measure(input_path, sample_rate, channel_count)

    # Step 2: decide where the hiss sits.
    # If even the quietest moments are louder than -30 dB, the track has no quiet gaps (dense,
    # loud music), so that "floor" is music, not hiss. Then use a gentle default instead.
    noise_floor = before["noise_floor_dbfs"]
    if noise_floor is None or noise_floor > MUSIC_NOT_HISS_DB:
        noise_floor = DEFAULT_NOISE_FLOOR_DB

    # Step 3: run the repair filters into a new file, in the same format (and at least the
    # same bitrate) as the original
    extension = output_extension(input_path, file_info["codec"], output_format)
    output_path = output_path_for(input_path, "repaired", output, extension)
    filter_chain = build_filter_chain(declick, declip, denoise, strength, noise_floor)
    encoder_args = encoder_options(extension, file_info, standard_bitrate_at_least(file_info["bitrate_kbps"]))
    run_filter(input_path, output_path, filter_chain, output_sample_rate(extension, sample_rate), encoder_args)

    # Step 4: measure the result
    after = measure(output_path, sample_rate, channel_count)
    return output_path, before, after
