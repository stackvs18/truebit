# End-to-end tests: make real test audio with FFmpeg, then check TrueBit's verdicts.
# Run with:  uv run pytest

import subprocess

import numpy as np
import pytest

from truebit.report import analyze_file
from truebit.spectrum import find_cutoff, power_spectrum
from truebit.verdict import likely_source


# Makes a few test files once: real lossless, MP3s, and fakes made from the MP3s
@pytest.fixture(scope="session")
def audio_folder(tmp_path_factory):
    folder = tmp_path_factory.mktemp("audio")

    def ffmpeg(*arguments):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)

    ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:r=44100:a=0.3", "-ac", "2", str(folder / "real.flac"))
    ffmpeg("-i", str(folder / "real.flac"), "-b:a", "128k", str(folder / "mp3_128.mp3"))
    ffmpeg("-i", str(folder / "real.flac"), "-b:a", "320k", str(folder / "mp3_320.mp3"))
    ffmpeg("-i", str(folder / "mp3_128.mp3"), str(folder / "fake.flac"))
    ffmpeg("-i", str(folder / "mp3_128.mp3"), "-b:a", "320k", str(folder / "fake_320.mp3"))
    return folder


def test_real_lossless_is_genuine(audio_folder):
    report = analyze_file(audio_folder / "real.flac")
    assert report["verdict"] == "lossless"
    assert report["spectrum"]["cutoff_hz"] is None


def test_flac_made_from_mp3_is_fake(audio_folder):
    report = analyze_file(audio_folder / "fake.flac")
    assert report["verdict"] == "fake_lossless"
    assert "128" in report["verdict_headline"]


def test_reencoded_320_is_fake(audio_folder):
    report = analyze_file(audio_folder / "fake_320.mp3")
    assert report["verdict"] == "fake_bitrate"


def test_honest_mp3s_are_just_lossy(audio_folder):
    assert analyze_file(audio_folder / "mp3_128.mp3")["verdict"] == "lossy"
    report_320 = analyze_file(audio_folder / "mp3_320.mp3")
    assert report_320["verdict"] == "lossy"
    assert report_320["spectrum"]["cutoff_hz"] >= 19800


def test_report_has_the_expected_shape(audio_folder):
    report = analyze_file(audio_folder / "real.flac")
    for key in ["verdict", "verdict_headline", "verdict_detail", "file", "loudness", "spectrum"]:
        assert key in report
    assert report["file"]["sample_rate_hz"] == 44100
    assert report["loudness"]["integrated_lufs"] is not None


def test_cutoff_finder_on_synthetic_spectrum():
    # White noise with everything above 16 kHz removed: the cliff must be found near 16 kHz
    sample_rate = 44100
    noise = np.random.default_rng(1).standard_normal(sample_rate * 4).astype(np.float32)
    spectrum = np.fft.rfft(noise)
    frequencies = np.fft.rfftfreq(len(noise), 1 / sample_rate)
    spectrum[frequencies > 16000] = 0
    filtered = np.fft.irfft(spectrum).astype(np.float32)

    freqs, levels = power_spectrum(filtered, sample_rate)
    cutoff_hz, drop_db = find_cutoff(freqs, levels, sample_rate)
    assert 15500 <= cutoff_hz <= 16500
    assert drop_db > 40


def test_source_table():
    assert likely_source(16750)[0] == "~128 kbps"
    assert likely_source(20000)[0] == "~320 kbps"
    assert likely_source(None) == (None, None)
