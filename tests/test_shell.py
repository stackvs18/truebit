# Tests for interactive mode: reading typed commands and pasted paths.

from truebit.shell import split_command, to_command_words


def test_quoted_windows_paths_stay_together():
    words = split_command('check "C:\\Users\\me\\Music\\my song.mp3" --save')
    assert words == ["check", "C:\\Users\\me\\Music\\my song.mp3", "--save"]


def test_extra_spaces_are_ignored():
    assert split_command("  scan    D:\\Music  ") == ["scan", "D:\\Music"]


def test_known_commands_pass_through():
    assert to_command_words(["check", "a.flac"]) == ["check", "a.flac"]
    assert to_command_words(["COMPARE", "a.flac", "b.mp3"]) == ["compare", "a.flac", "b.mp3"]


def test_typing_truebit_inside_truebit_is_fine():
    assert to_command_words(["truebit", "scan", "x"]) == ["scan", "x"]


def test_a_pasted_file_is_checked_and_a_folder_is_scanned(tmp_path):
    song = tmp_path / "song.flac"
    song.write_bytes(b"not really audio")
    assert to_command_words([str(song)]) == ["check", str(song)]
    assert to_command_words([str(tmp_path)]) == ["scan", str(tmp_path)]


def test_unknown_words_are_rejected():
    assert to_command_words(["dance"]) is None
    assert to_command_words([]) is None
