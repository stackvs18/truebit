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
