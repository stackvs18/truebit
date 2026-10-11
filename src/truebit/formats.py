# Every audio format TrueBit understands, and how to write each one.
#
# Reading: FFmpeg decodes all of these, so every command (check, scan, compare, repair,
#          normalize, fix) works on any of them.
# Writing: repair, normalize and fix save the result in the SAME format as the original
#          (an MP3 stays an MP3, an M4A stays an M4A), unless you choose another with --format.
#          Saving an MP3 as FLAC would make TrueBit's own output a "fake lossless" file.

from pathlib import Path

# File extensions TrueBit looks for (scan, fix, the upload page)
LOSSLESS_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif", ".alac", ".ape", ".wv", ".tta"}
LOSSY_EXTENSIONS = {".mp3", ".mp2", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus", ".wma",
                    ".ac3", ".eac3", ".amr", ".3gp"}
MIXED_EXTENSIONS = {".mka", ".webm", ".caf"}  # containers that can hold either kind
AUDIO_EXTENSIONS = LOSSLESS_EXTENSIONS | LOSSY_EXTENSIONS | MIXED_EXTENSIONS

# Codecs that throw sound away when they compress (lossy). Every other codec is lossless.
# (An .m4a can be either: AAC is lossy, ALAC is lossless, so we always look at the codec.)
LOSSY_CODECS = {"mp3", "mp3float", "mp2", "aac", "aac_latm", "vorbis", "opus", "wmav1", "wmav2",
                "wmapro", "wmavoice", "ac3", "eac3", "amr_nb", "amr_wb", "atrac3", "cook"}

# The formats TrueBit can write: extension -> (FFmpeg encoder, is it lossy?)
WRITERS = {
    ".flac": ("flac", False),
    ".wav": ("pcm_le", False),
    ".aiff": ("pcm_be", False),
    ".aif": ("pcm_be", False),
    ".mp3": ("libmp3lame", True),
    ".m4a": ("aac", True),  # stays Apple Lossless (ALAC) if the original was ALAC
    ".m4b": ("aac", True),
    ".aac": ("aac", True),
    ".ogg": ("libvorbis", True),
    ".oga": ("libvorbis", True),
    ".opus": ("libopus", True),
    ".wma": ("wmav2", True),
}

# Formats whose files can carry cover art (we copy it across)
COVER_ART_EXTENSIONS = {".mp3", ".flac", ".m4a", ".m4b"}

# Standard bitrates for lossy files, in kbps
STANDARD_BITRATES = [96, 128, 160, 192, 224, 256, 320]


# The next standard bitrate at or above the one given (e.g. 250 -> 256, 320 -> 320).
# Used when re-saving a lossy file, so it never gets a lower bitrate than it had.
def standard_bitrate_at_least(kbps):
    if kbps is None:
        return 256
    for standard in STANDARD_BITRATES:
        if standard >= kbps:
            return standard
    return STANDARD_BITRATES[-1]


# An honest bitrate for sound that really holds `real_kbps` of detail: one step above it
# (so re-encoding adds no audible loss) but below 1.4 times it (TrueBit's "fake" limit),
# e.g. 128 -> 160, 192 -> 224, 256 -> 320.
def honest_bitrate(real_kbps):
    for standard in STANDARD_BITRATES:
        if standard > real_kbps and standard < real_kbps * 1.4:
            return standard
    return standard_bitrate_at_least(real_kbps)


# The extension to save as: the one chosen with --format, else the original's own.
# Formats TrueBit can't write (APE, WavPack, AC3...) become FLAC (lossless) or M4A (lossy).
def output_extension(input_path, codec, chosen_format=None):
    if chosen_format:
        extension = "." + chosen_format.lower().lstrip(".")
        if extension not in WRITERS:
            raise ValueError("Can't save as " + chosen_format + ". Choose one of: "
                             + ", ".join(sorted(name.lstrip(".") for name in WRITERS)))
        return extension

    extension = Path(input_path).suffix.lower()
    if extension in WRITERS:
        return extension
    if codec in LOSSY_CODECS:
        return ".m4a"
    return ".flac"


# The sample rate to write: the original, except where the format can't hold it
def output_sample_rate(extension, sample_rate):
    encoder, is_lossy = WRITERS[extension]
    if extension == ".opus":
        return 48000  # Opus always works at 48 kHz
    if is_lossy and sample_rate > 48000:
        # MP3 and friends stop at 48 kHz: 88.2/176.4 kHz -> 44.1 kHz, 96/192 kHz -> 48 kHz
        if sample_rate % 44100 == 0:
            return 44100
        return 48000
    return sample_rate


# The FFmpeg options that write a file with this extension.
# file_info = the original's details (for bit depth and codec); bitrate_kbps is for lossy formats.
def encoder_options(extension, file_info, bitrate_kbps):
    encoder, is_lossy = WRITERS[extension]
    bit_depth = file_info.get("bit_depth") or 16

    # Step 1: lossless formats keep the original bit depth (16- or 24-bit)
    if encoder == "pcm_le" or encoder == "pcm_be":
        size = "24" if bit_depth > 16 else "16"
        ending = "be" if encoder == "pcm_be" else "le"
        return ["-c:a", "pcm_s" + size + ending]
    if encoder == "flac":
        sample_format = "s32" if bit_depth > 16 else "s16"  # FLAC stores 24-bit audio as s32
        return ["-c:a", "flac", "-sample_fmt", sample_format]

    # Step 2: an M4A that held Apple Lossless stays Apple Lossless
    if extension in (".m4a", ".m4b") and file_info.get("codec") == "alac":
        return ["-c:a", "alac"]

    # Step 3: lossy formats need a bitrate
    return ["-c:a", encoder, "-b:a", f"{bitrate_kbps}k"]
