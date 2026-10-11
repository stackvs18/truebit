# Turns the cutoff frequency into a verdict a person can understand.
#
# Each encoder setting removes everything above a typical frequency:
#   below 17.25 kHz      -> about 128 kbps  (LAME's 128 kbps low-pass is ~16.7-17 kHz)
#   17.25 to 18.8 kHz    -> about 160-192 kbps
#   18.8 to 19.8 kHz     -> about 256 kbps (or MP3 V0)
#   19.8 to 20.8 kHz     -> about 320 kbps
#   no cliff             -> consistent with real lossless
# These are estimates: different encoders use slightly different cutoffs.
# Calibrated on files made with FFmpeg's MP3 encoder (LAME).

SOURCE_TABLE = [
    (17250, "~128 kbps", 128),
    (18800, "~160-192 kbps", 192),
    (19800, "~256 kbps", 256),
    (20800, "~320 kbps", 320),
]


# The likely original quality for a cutoff, e.g. ("~128 kbps", 128), or (None, None) for no cliff
def likely_source(cutoff_hz):
    if cutoff_hz is None:
        return None, None
    for upper_limit, label, kbps in SOURCE_TABLE:
        if cutoff_hz < upper_limit:
            return label, kbps
    return None, None  # cliff above 20.8 kHz: no real lossy fingerprint


# The verdict: (key, headline, detail)
def make_verdict(file_info, spectrum):
    source_label, source_kbps = likely_source(spectrum["cutoff_hz"])
    cutoff_khz = spectrum["cutoff_hz"] / 1000 if spectrum["cutoff_hz"] else None

    # A lossless container (FLAC, WAV, ALAC...) with a lossy cliff: it was upscaled
    if not file_info["lossy_codec"]:
        if source_label is not None:
            return ("fake_lossless", "FAKE LOSSLESS: upscaled from " + source_label,
                    f"This {file_info['codec'].upper()} file has a sharp cutoff at {cutoff_khz:.1f} kHz, "
                    f"the fingerprint of a {source_label} lossy file. Converting a lossy file to a "
                    "lossless format makes it bigger but brings nothing back.")
        return ("lossless", "GENUINE LOSSLESS",
                "Sound reaches all the way up the spectrum with no encoder cutoff. "
                "Consistent with a real lossless source.")

    # A lossy file claiming a higher bitrate than its cutoff suggests
    claimed = file_info["bitrate_kbps"]
    if source_kbps is not None and claimed is not None and claimed >= source_kbps * 1.4:
        return ("fake_bitrate", f"FAKE {claimed} kbps: really {source_label}",
                f"It claims {claimed} kbps, but the cutoff at {cutoff_khz:.1f} kHz matches a "
                f"{source_label} source. It was re-encoded at a higher bitrate.")

    return ("lossy", "This is a lossy file",
            "The file is stored in a lossy format, so some of the original sound was discarded "
            "when it was encoded. Converting it to WAV or FLAC makes the file bigger but brings "
            "nothing back.")


# The three bitrates side by side:
#   label_kbps   what the file's properties say (what a music player shows)
#   stored_kbps  what's really stored: the file's size divided by its length
#   real_kbps    what the sound is really worth, judged from the cutoff (None = no cutoff)
def bitrate_truth(file_info, spectrum):
    source_label, source_kbps = likely_source(spectrum["cutoff_hz"])
    label_kbps = file_info["bitrate_kbps"]

    # The cutoff -> bitrate table was measured on MP3s. It fits MP3s, and "lossless" files that
    # were made from MP3s. AAC, Opus and Vorbis keep more treble per kbps, so for them we only
    # say where the sound stops and which MP3 it looks like.
    is_mp3_like = file_info["codec"] in ("mp3", "mp3float") or not file_info["lossy_codec"]

    # Step 1: describe the real quality in words
    if source_kbps is None:
        if file_info["lossy_codec"]:
            real_text = "full band (no encoder cutoff found)"
        else:
            real_text = "lossless"
    elif is_mp3_like:
        real_text = source_label
    else:
        cutoff_khz = spectrum["cutoff_hz"] / 1000
        real_text = f"sound stops at {cutoff_khz:.1f} kHz (like a {source_label} MP3)"
        source_kbps = None

    # Step 2: how many times bigger the label is than the real quality (2.5 = "2.5x inflated")
    inflated_times = None
    if source_kbps is not None and label_kbps:
        inflated_times = round(label_kbps / source_kbps, 1)

    return {
        "label_kbps": label_kbps,
        "stored_kbps": file_info["data_rate_kbps"],
        "real_kbps": source_kbps,
        "real_text": real_text,
        "inflated_times": inflated_times,
        "mode": file_info["bitrate_mode"],
    }


# A plain answer to "is this file lossless?": (True/False, one sentence)
def lossless_answer(file_info, verdict_key):
    codec = file_info["codec"].upper()
    if verdict_key == "lossless":
        return True, f"Yes. {codec} is a lossless format and the sound reaches the top of the spectrum."
    if verdict_key == "fake_lossless":
        return False, f"No. {codec} is a lossless format, but the sound inside came from a lossy file."
    return False, f"No. {codec} is a lossy format: some sound was thrown away when it was encoded."
