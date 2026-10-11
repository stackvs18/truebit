# Finds the "cliff": the frequency where the sound suddenly stops.
#
# Real lossless audio has sound all the way up to the top (about 22 kHz for CD audio).
# MP3 and AAC encoders throw away high frequencies to save space: a 128 kbps MP3 cuts
# everything above about 16 kHz. Converting that MP3 to FLAC can't bring them back, so a
# "FLAC" with a sharp cliff at 16 kHz was really made from a 128 kbps MP3.
#
# How:
#   1. Welch's method: split the audio into short overlapping pieces, take the FFT of each
#      (how much energy at each frequency), and average them -> one smooth spectrum.
#   2. Measure the average level in 250 Hz bands from 14 kHz upwards.
#   3. The cliff is where the level drops the most between neighbouring bands, if that drop is
#      big (20 dB or more) and everything above it stays quiet.

import numpy as np
from scipy.signal import welch

BAND_WIDTH_HZ = 250
SEARCH_FROM_HZ = 14000
MIN_CLIFF_DB = 20
SILENCE_DB = -300.0  # what we report for a band with no sound at all

# The bands shown in reports (same as the analyzer screenshots in context/Sources)
REPORT_BANDS = [(12000, 14000), (14000, 15000), (15000, 16000), (16000, 17000), (17000, 18000),
                (18000, 19000), (19000, 20000), (20000, 20500), (20500, 21000), (21000, 22050)]


# The averaged spectrum: frequencies (Hz) and their levels (dB)
def power_spectrum(samples, sample_rate):
    frequencies, power = welch(samples, fs=sample_rate, nperseg=8192)
    levels_db = 10 * np.log10(power + 1e-30)
    return frequencies, levels_db


# The average level (dB) between two frequencies, or SILENCE_DB if there's nothing there
def average_level(frequencies, levels_db, from_hz, to_hz):
    inside = (frequencies >= from_hz) & (frequencies < to_hz)
    if not np.any(inside):
        return None
    level = float(np.mean(levels_db[inside]))
    return max(level, SILENCE_DB)


# Looks for the cliff. Returns (cutoff_hz, drop_db), or (None, 0.0) if there's no cliff.
def find_cutoff(frequencies, levels_db, sample_rate):
    nyquist = sample_rate / 2

    # Step 1: level of every 250 Hz band from 14 kHz to the top
    band_starts = []
    band_levels = []
    start = SEARCH_FROM_HZ
    while start + BAND_WIDTH_HZ <= nyquist - BAND_WIDTH_HZ:
        level = average_level(frequencies, levels_db, start, start + BAND_WIDTH_HZ)
        if level is not None:
            band_starts.append(start)
            band_levels.append(level)
        start = start + BAND_WIDTH_HZ

    if len(band_levels) < 4:
        return None, 0.0

    # Step 2: the biggest drop between a band and the band two steps above it
    best_position = None
    best_drop = 0.0
    for position in range(len(band_levels) - 2):
        drop = band_levels[position] - band_levels[position + 2]
        if drop > best_drop:
            best_drop = drop
            best_position = position

    # Step 3: is it a real cliff? Big drop, and quiet above it compared to below it.
    if best_position is None or best_drop < MIN_CLIFF_DB:
        return None, 0.0
    below = np.mean(band_levels[: best_position + 1])
    above = np.mean(band_levels[best_position + 2:])
    if above > below - MIN_CLIFF_DB:
        return None, 0.0

    cutoff_hz = band_starts[best_position + 1]
    total_drop = float(below - above)
    return float(cutoff_hz), round(total_drop, 1)


# The frequency below which 85% of the energy sits (a common "brightness" measure)
def rolloff_frequency(frequencies, levels_db, share=0.85):
    power = 10 ** (levels_db / 10)
    cumulative = np.cumsum(power)
    index = int(np.searchsorted(cumulative, share * cumulative[-1]))
    return float(frequencies[min(index, len(frequencies) - 1)])


# Everything the report needs about the spectrum
def analyze_spectrum(samples, sample_rate):
    frequencies, levels_db = power_spectrum(samples, sample_rate)
    cutoff_hz, drop_db = find_cutoff(frequencies, levels_db, sample_rate)
    nyquist = sample_rate / 2

    bands = []
    for from_hz, to_hz in REPORT_BANDS:
        if from_hz >= nyquist:
            continue
        level = average_level(frequencies, levels_db, from_hz, min(to_hz, nyquist))
        bands.append({"from_hz": from_hz, "to_hz": min(to_hz, int(nyquist)),
                      "level_db": round(level, 1) if level is not None else SILENCE_DB})

    return {
        "cutoff_hz": int(cutoff_hz) if cutoff_hz is not None else None,
        "cutoff_drop_db": drop_db,
        "nyquist_hz": int(nyquist),
        "rolloff_median_hz": int(rolloff_frequency(frequencies, levels_db)),
        "bands": bands,
    }
