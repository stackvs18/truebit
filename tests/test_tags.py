# Tests for `truebit tags`: reading every tag, changing them for good in every format,
# cover art, and making sure the audio itself never changes.

import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from truebit.cli import app
from truebit.probe import probe
from truebit.tags import TagError, change_tags, read_all_tags, save_cover


def ffmpeg(*arguments):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)


# A fingerprint of the decoded sound: equal fingerprints = exactly the same audio
def audio_fingerprint(path):
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "md5", "-"],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture(scope="module")
def originals(tmp_path_factory):
    folder = tmp_path_factory.mktemp("tag_originals")
    source = str(folder / "source.flac")
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=2:c=pink:r=44100:a=0.3", "-ac", "2", source)
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=32x32:d=1", "-frames:v", "1", str(folder / "cover.png"))
    makers = {
        "song.mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
        "song.flac": ["-c:a", "flac"],
        "song.m4a": ["-c:a", "aac", "-b:a", "128k"],
        "song.ogg": ["-c:a", "libvorbis"],
        "song.opus": ["-c:a", "libopus"],
        "song.wma": ["-c:a", "wmav2"],
        "song.wav": [],
        "song.aiff": [],
        "song.aac": ["-c:a", "aac", "-b:a", "128k"],
    }
    for name, options in makers.items():
        ffmpeg("-i", source, *options, str(folder / name))
    return folder


# A fresh copy of one original, so every test starts clean
def fresh_copy(originals, name, tmp_path):
    path = tmp_path / name
    shutil.copy(originals / name, path)
    return path


@pytest.mark.parametrize("name", ["song.mp3", "song.flac", "song.m4a", "song.ogg", "song.opus", "song.wma",
                                  "song.wav", "song.aiff"])
def test_tags_change_for_good_and_the_sound_stays_the_same(originals, tmp_path, name):
    path = fresh_copy(originals, name, tmp_path)
    fingerprint_before = audio_fingerprint(path)

    change_tags(path, {"title": "Don't Stop", "artist": "TrueBit", "year": "2024", "track": "3/12",
                       "comment": "hello", "mood": "happy"})
    tags = dict(read_all_tags(path)["tags"])
    assert tags["title"] == "Don't Stop"
    assert tags["track"] == "3/12"
    assert tags["mood"] == "happy"           # any other tag name works too
    assert probe(path)["tags"]["title"] == "Don't Stop"  # FFmpeg sees the new title as well

    change_tags(path, remove_names=["comment", "mood"])
    tags = dict(read_all_tags(path)["tags"])
    assert "comment" not in tags and "mood" not in tags

    assert audio_fingerprint(path) == fingerprint_before  # only the tags changed


@pytest.mark.parametrize("name", ["song.mp3", "song.flac", "song.m4a", "song.ogg", "song.opus", "song.wav"])
def test_cover_art_can_be_added_saved_and_removed(originals, tmp_path, name):
    path = fresh_copy(originals, name, tmp_path)
    change_tags(path, cover_path=originals / "cover.png")
    assert read_all_tags(path)["cover"]["mime"] == "image/png"

    saved = save_cover(path, tmp_path / "exported")
    assert saved.read_bytes() == (originals / "cover.png").read_bytes()

    change_tags(path, take_out_cover=True)
    assert read_all_tags(path)["cover"] is None


def test_clear_removes_every_tag_and_the_cover(originals, tmp_path):
    path = fresh_copy(originals, "song.flac", tmp_path)
    change_tags(path, {"title": "x", "artist": "y"}, cover_path=originals / "cover.png")
    change_tags(path, clear_all=True)
    info = read_all_tags(path)
    assert info["tags"] == [] and info["cover"] is None


def test_output_changes_a_copy_and_leaves_the_original_alone(originals, tmp_path):
    path = fresh_copy(originals, "song.mp3", tmp_path)
    original_bytes = path.read_bytes()
    copy_path = change_tags(path, {"title": "Copy"}, output_path=tmp_path / "copy.mp3")
    assert dict(read_all_tags(copy_path)["tags"])["title"] == "Copy"
    assert path.read_bytes() == original_bytes


def test_raw_aac_explains_that_it_cant_hold_tags(originals, tmp_path):
    path = fresh_copy(originals, "song.aac", tmp_path)
    with pytest.raises(TagError):
        change_tags(path, {"title": "x"})


def test_command_asks_before_changing_and_yes_skips_the_question(originals, tmp_path):
    path = fresh_copy(originals, "song.mp3", tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["tags", str(path), "--set", "title=Asked"], input="n\n")
    assert result.exit_code == 0
    assert "title" not in dict(read_all_tags(path)["tags"])

    result = runner.invoke(app, ["tags", str(path), "--set", "title=Sure", "--yes"])
    assert result.exit_code == 0
    assert dict(read_all_tags(path)["tags"])["title"] == "Sure"


def test_m4a_yes_no_flags_from_itunes_are_read(originals, tmp_path):
    # Regression: real iTunes files store "compilation" and "gapless" as True/False, not a list
    from mutagen.mp4 import MP4
    path = fresh_copy(originals, "song.m4a", tmp_path)
    audio = MP4(path)
    audio["cpil"] = True
    audio["pgap"] = False
    audio.save()
    tags = dict(read_all_tags(path)["tags"])
    assert tags["compilation"] == "True"
    assert tags["gapless"] == "False"
