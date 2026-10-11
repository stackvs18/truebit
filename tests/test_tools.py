# Tests for repair, normalize and compare, on audio made with FFmpeg.

import subprocess

import pytest

from truebit.compare import compare_files
from truebit.normalize import normalize_file
from truebit.repair import build_filter_chain, repair_file


def ffmpeg(*arguments):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    folder = tmp_path_factory.mktemp("tools")
    # Damaged: loud tone bursts that clip, with hiss in between
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,1),0.5), 1.6*sin(2*PI*440*t), 0)':s=44100:d=4",
           "-f", "lavfi", "-i", "anoisesrc=d=4:c=white:r=44100:a=0.03",
           "-filter_complex", "[0][1]amix=inputs=2:normalize=0", "-sample_fmt", "s16",
           str(folder / "damaged.flac"))
    # Quiet: pink noise far below streaming loudness
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:r=44100:a=0.02", str(folder / "quiet.flac"))
    # A real lossless file, and a fake made from a 128 kbps MP3 of it
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:r=44100:a=0.3", str(folder / "real.flac"))
    ffmpeg("-i", str(folder / "real.flac"), "-b:a", "128k", str(folder / "small.mp3"))
    ffmpeg("-i", str(folder / "small.mp3"), str(folder / "fake.flac"))
    return folder


def test_repair_removes_clipping_and_reduces_noise(folder):
    output_path, before, after = repair_file(folder / "damaged.flac", strength="strong")
    assert output_path.exists()
    assert before["clipped_samples"] > 1000
    assert after["clipped_samples"] == 0
    assert after["noise_floor_dbfs"] < before["noise_floor_dbfs"] - 5  # at least 5 dB quieter
    assert after["true_peak_dbtp"] < 0


def test_repair_steps_can_be_switched_off():
    chain = build_filter_chain(declick=False, declip=True, denoise=False)
    assert "adeclick" not in chain
    assert "afftdn" not in chain
    assert "adeclip" in chain


def test_repair_rejects_unknown_strength(folder):
    with pytest.raises(ValueError):
        repair_file(folder / "damaged.flac", strength="nuclear")


def test_normalize_hits_the_target(folder):
    output_path, before, after = normalize_file(folder / "quiet.flac", target_lufs=-14)
    assert output_path.exists()
    assert before["integrated_lufs"] < -30
    assert abs(after["integrated_lufs"] - (-14)) <= 1.0
    assert after["true_peak_dbtp"] <= -0.5


def test_compare_prefers_real_lossless_even_with_lower_bitrate(folder):
    result = compare_files(folder / "fake.flac", folder / "real.flac")
    assert result["winner"] == "real.flac"
    assert "genuine lossless" in result["reason"]


def test_clean_loud_stereo_is_not_called_clipped(tmp_path):
    # Regression: mixing stereo to mono by ADDING channels made a 0.9 peak look like 1.8
    path = tmp_path / "loud_stereo.flac"
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*440*t)|0.9*sin(2*PI*440*t)':s=44100:d=3",
           str(path))
    from truebit.report import analyze_file
    report = analyze_file(path)
    assert report["loudness"]["clipped_samples"] == 0
    assert report["loudness"]["sample_peak_dbfs"] < 0


def test_normalize_works_on_a_master_louder_than_0_lufs(tmp_path):
    # Regression: loudnorm refuses measured_I above 0, and real loud masters measure +0.78
    path = tmp_path / "very_loud.flac"
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.99*sgn(sin(2*PI*1000*t))|0.99*sgn(sin(2*PI*1000*t))':s=44100:d=4",
           str(path))
    output_path, before, after = normalize_file(path, target_lufs=-14)
    assert before["integrated_lufs"] > -2
    assert after["integrated_lufs"] < -10


def test_compare_same_file_is_a_tie(folder):
    result = compare_files(folder / "real.flac", folder / "real.flac")
    assert result["winner"] is None
