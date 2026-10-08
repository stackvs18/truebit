# `truebit compare a b`: which of two copies of a song is genuinely better?
#
# Bitrate on the label means nothing (that's the whole point of TrueBit), so we rank by what's
# really in the file:
#   1. genuine lossless beats everything
#   2. otherwise, the higher real cutoff wins (more real high-frequency detail)
#   3. ties are broken by fewer clipped samples, then by a higher sample rate / bit depth

from pathlib import Path

from truebit.report import analyze_file

MAX_DURATION_DIFFERENCE_SECONDS = 3


# A number for "how much real detail is in this file" (bigger = better)
def quality_points(report):
    file_info = report["file"]
    spectrum = report["spectrum"]

    if report["verdict"] == "lossless":
        points = 1000.0
        points = points + file_info["sample_rate_hz"] / 1000  # 96 kHz > 44.1 kHz
        points = points + (file_info["bit_depth"] or 16)  # 24-bit > 16-bit
    elif spectrum["cutoff_hz"] is not None:
        points = spectrum["cutoff_hz"] / 100  # e.g. 20 kHz cutoff -> 200 points
    else:
        points = spectrum["nyquist_hz"] / 100  # lossy file without a clear cliff

    # Clipping damages the sound
    if report["loudness"]["clipped_samples"] > 0:
        points = points - 5
    return points


# Explains in one sentence why the winner won
def reason(winner, loser):
    if winner["verdict"] == "lossless" and loser["verdict"] != "lossless":
        return "It's genuine lossless; the other one isn't."
    winner_cutoff = winner["spectrum"]["cutoff_hz"]
    loser_cutoff = loser["spectrum"]["cutoff_hz"]
    if winner_cutoff and loser_cutoff and winner_cutoff != loser_cutoff:
        return (f"Its real cutoff is higher ({winner_cutoff / 1000:.1f} kHz vs "
                f"{loser_cutoff / 1000:.1f} kHz), so more real detail survived.")
    if loser["loudness"]["clipped_samples"] > winner["loudness"]["clipped_samples"]:
        return "The other one has clipping (distortion)."
    return "Higher sample rate or bit depth."


# Analyses both files and decides. Returns a dict with both reports and the result.
def compare_files(first_path, second_path):
    first = analyze_file(first_path)
    second = analyze_file(second_path)

    first_points = quality_points(first)
    second_points = quality_points(second)

    duration_gap = abs(first["file"]["duration_seconds"] - second["file"]["duration_seconds"])
    warning = None
    if duration_gap > MAX_DURATION_DIFFERENCE_SECONDS:
        warning = f"The lengths differ by {duration_gap:.0f} s; these may not be the same recording."

    if abs(first_points - second_points) < 0.01:
        winner = None
        explanation = "Both copies have the same real quality. Keep the smaller one."
    elif first_points > second_points:
        winner = Path(first_path).name
        explanation = reason(first, second)
    else:
        winner = Path(second_path).name
        explanation = reason(second, first)

    return {
        "first": {"file": Path(first_path).name, "report": first, "points": round(first_points, 1)},
        "second": {"file": Path(second_path).name, "report": second, "points": round(second_points, 1)},
        "winner": winner,
        "reason": explanation,
        "warning": warning,
    }
