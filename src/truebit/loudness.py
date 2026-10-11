# Loudness: how loud the track is and whether it clips.
#
#   integrated_lufs   overall loudness (EBU R128, what Spotify/YouTube normalise to)
#   true_peak_dbtp    the highest peak, including between samples (above 0 = distortion risk)
#   crest_factor_db   peak minus average: low = heavily compressed ("loudness war")
#   clipped_samples   samples stuck at full scale

import re
import subprocess

import numpy as np


# Runs FFmpeg's ebur128 filter and reads its summary: (lufs, range, true peak)
def ebu_r128(file_path):
    command = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(file_path),
               "-af", "ebur128=peak=true", "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    summary = result.stderr.split("Summary:")[-1]

    def read_number(pattern):
        match = re.search(pattern, summary)
        if match is None:
            return None
        return float(match.group(1))

    return (read_number(r"I:\s+(-?[\d.]+) LUFS"),
            read_number(r"LRA:\s+(-?[\d.]+) LU"),
            read_number(r"Peak:\s+(-?[\d.]+|-inf) dBFS"))


# Converts a level (0 to 1) to decibels
def to_db(value):
    return round(20 * np.log10(max(value, 1e-15)), 1)


# Everything for the "loudness" part of the report
# samples = every channel, interleaved (so peaks and clipping are measured on the real signal)
def analyze_loudness(file_path, samples, sample_rate, channel_count=1):
    integrated, loudness_range, true_peak = ebu_r128(file_path)

    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

    # Noise floor: the quietest 5% of 50 ms windows (a window holds every channel's samples)
    window = max(int(sample_rate * 0.05) * channel_count, 1)
    window_count = len(samples) // window
    noise_floor_db = None
    if window_count > 0:
        windows = samples[: window_count * window].reshape(window_count, window).astype(np.float64)
        window_rms = np.sqrt(np.mean(windows ** 2, axis=1))
        noise_floor_db = to_db(float(np.percentile(window_rms, 5)))

    return {
        "integrated_lufs": integrated,
        "loudness_range_lu": loudness_range,
        "true_peak_dbtp": true_peak,
        "sample_peak_dbfs": to_db(peak),
        "rms_dbfs": to_db(rms),
        "crest_factor_db": round(to_db(peak) - to_db(rms), 1),
        "noise_floor_dbfs": noise_floor_db,
        "clipped_samples": int(np.sum(np.abs(samples) >= 0.999)),
    }
