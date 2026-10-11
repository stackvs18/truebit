# Tests for every audio format, the three bitrates (says / stores / really), tags and cover art,
# and the fix command. All audio is made with FFmpeg.

import shutil
import subprocess

import pytest

from truebit.fix import fix_file, fix_many
from truebit.formats import honest_bitrate, output_extension, standard_bitrate_at_least
from truebit.normalize import normalize_file
from truebit.probe import probe
from truebit.report import analyze_file


def ffmpeg(*arguments):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    folder = tmp_path_factory.mktemp("formats")
    real = str(folder / "real.flac")
    # A real lossless file, a 128 kbps MP3 of it, and two fakes made from that MP3
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:r=44100:a=0.3", "-ac", "2", real)
    ffmpeg("-i", real, "-b:a", "128k", str(folder / "small.mp3"))
    ffmpeg("-i", str(folder / "small.mp3"), str(folder / "fake.flac"))
    ffmpeg("-i", str(folder / "small.mp3"), "-b:a", "320k", str(folder / "fake_320.mp3"))
    # A variable-bitrate MP3
    ffmpeg("-i", real, "-q:a", "2", str(folder / "vbr.mp3"))
    # An MP3 with tags and cover art
    ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-frames:v", "1", str(folder / "cover.png"))
    ffmpeg("-i", real, "-i", str(folder / "cover.png"), "-map", "0:a", "-map", "1:v", "-c:v", "copy",
           "-disposition:v", "attached_pic", "-metadata", "title=Test Song", "-metadata", "artist=TrueBit",
           "-b:a", "256k", str(folder / "tagged.mp3"))
    # A noisy recording: tone bursts with steady hiss in the gaps
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,2),1.2), 0.5*sin(2*PI*440*t), 0)':s=44100:d=6",
           "-f", "lavfi", "-i", "anoisesrc=d=6:c=white:r=44100:a=0.01",
           "-filter_complex", "[0][1]amix=inputs=2:normalize=0", str(folder / "noisy.flac"))
    return folder


# name, FFmpeg options to make it, is it lossy?
FORMATS = [
    ("song.mp3", ["-c:a", "libmp3lame", "-b:a", "192k"], True),
    ("song.m4a", ["-c:a", "aac", "-b:a", "192k"], True),
    ("song.aac", ["-c:a", "aac", "-b:a", "128k"], True),
    ("song.ogg", ["-c:a", "libvorbis", "-b:a", "160k"], True),
    ("song.opus", ["-c:a", "libopus", "-b:a", "128k"], True),
    ("song.wma", ["-c:a", "wmav2", "-b:a", "192k"], True),
    ("song.wav", [], False),
    ("song.aiff", [], False),
    ("apple.m4a", ["-c:a", "alac"], False),
]


@pytest.mark.parametrize("name, options, is_lossy", FORMATS)
def test_every_format_is_checked_and_normalized_in_its_own_format(folder, name, options, is_lossy):
    path = folder / name
    ffmpeg("-i", str(folder / "real.flac"), *options, str(path))

    report = analyze_file(path)
    assert report["file"]["lossy_codec"] == is_lossy
    assert report["lossless"]["is_lossless"] == (not is_lossy)
    assert report["bitrate"]["stored_kbps"] > 0

    output_path, before, after = normalize_file(path)
    assert output_path.suffix == path.suffix
    assert probe(output_path)["codec"] == probe(path)["codec"]  # an MP3 stays an MP3, ALAC stays ALAC
    assert abs(after["integrated_lufs"] - (-14)) <= 1.0


def test_bitrate_says_stores_and_really(folder):
    bitrate = analyze_file(folder / "fake_320.mp3")["bitrate"]
    assert bitrate["label_kbps"] == 320        # what the properties say
    assert 300 <= bitrate["stored_kbps"] <= 340  # size / length
    assert bitrate["real_kbps"] == 128         # what the sound is really worth
    assert bitrate["inflated_times"] == 2.5
    assert bitrate["mode"] == "CBR"


def test_variable_bitrate_mp3_is_detected(folder):
    assert probe(folder / "vbr.mp3")["bitrate_mode"] == "VBR"


def test_tags_and_cover_art_are_read_and_kept(folder):
    info = probe(folder / "tagged.mp3")
    assert info["tags"]["title"] == "Test Song"
    assert info["has_cover_art"]

    output_path, before, after = normalize_file(folder / "tagged.mp3")
    kept = probe(output_path)
    assert kept["tags"]["artist"] == "TrueBit"
    assert kept["has_cover_art"]


def test_honest_and_standard_bitrates():
    assert honest_bitrate(128) == 160  # one step up, but under TrueBit's 1.4x "fake" limit
    assert honest_bitrate(256) == 320
    assert honest_bitrate(320) == 320
    assert standard_bitrate_at_least(250) == 256
    assert standard_bitrate_at_least(None) == 256


def test_output_format_choice():
    assert output_extension("a.mp3", "mp3") == ".mp3"
    assert output_extension("a.ape", "ape") == ".flac"  # can't write APE: lossless -> FLAC
    assert output_extension("a.ac3", "ac3") == ".m4a"   # can't write AC3: lossy -> M4A
    assert output_extension("a.flac", "flac", "mp3") == ".mp3"
    with pytest.raises(ValueError):
        output_extension("a.flac", "flac", "xyz")


def test_fix_turns_a_fake_lossless_file_into_an_honest_smaller_mp3(folder, tmp_path):
    result = fix_file(folder / "fake.flac", tmp_path)
    after = result["after"]
    assert result["output"].suffix == ".mp3"
    assert after["verdict"] == "lossy"  # TrueBit no longer calls it fake
    assert after["bitrate"]["label_kbps"] == 160
    assert after["file"]["file_size_bytes"] < result["before"]["file"]["file_size_bytes"] / 4
    assert abs(after["loudness"]["integrated_lufs"] - (-14)) <= 1.0


def test_fix_turns_a_fake_320_into_an_honest_160(folder, tmp_path):
    result = fix_file(folder / "fake_320.mp3", tmp_path)
    assert result["output"].suffix == ".mp3"
    assert result["after"]["verdict"] == "lossy"
    assert result["after"]["bitrate"]["label_kbps"] == 160


def test_fix_turns_down_background_hiss(folder, tmp_path):
    result = fix_file(folder / "noisy.flac", tmp_path)
    assert result["plan"]["denoise"]
    assert result["output"].suffix == ".flac"
    before_noise = result["before"]["loudness"]["noise_floor_dbfs"]
    assert result["after"]["loudness"]["noise_floor_dbfs"] < before_noise - 5


def test_fix_leaves_a_genuine_lossless_file_lossless(folder, tmp_path):
    result = fix_file(folder / "real.flac", tmp_path)
    assert result["plan"]["problems"] == []
    assert result["output"].suffix == ".flac"
    assert result["after"]["verdict"] == "lossless"


def test_fix_never_overwrites_two_files_with_the_same_name(folder, tmp_path):
    # fake.flac becomes fake.mp3, and there's already a different fake.mp3
    other_folder = tmp_path / "other"
    other_folder.mkdir()
    shutil.copy(folder / "small.mp3", other_folder / "fake.mp3")
    results = fix_many([folder / "fake.flac", other_folder / "fake.mp3"], tmp_path / "out")
    names = sorted(result["output"].name for result in results)
    assert names == ["fake (2).mp3", "fake.mp3"]


def test_fix_only_rebuilds_peaks_when_clipping_is_audible():
    from truebit.fix import plan_fix
    report = {"verdict": "lossy", "spectrum": {"cutoff_hz": None},
              "file": {"duration_seconds": 200, "sample_rate_hz": 44100, "channels": 2},
              "loudness": {"clipped_samples": 2296, "noise_floor_dbfs": -70}}
    assert not plan_fix(report)["declip"]  # 2,296 of 10.6 million samples: inaudible
    report["loudness"]["clipped_samples"] = 633714
    assert plan_fix(report)["declip"]      # 6% of samples: audible
