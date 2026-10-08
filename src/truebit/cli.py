# The `truebit` command.
#
#   truebit                          interactive mode (the truebit › prompt)
#   truebit check song.flac          lossless or not? the bitrate it says vs what it really holds
#   truebit scan "D:\Music"          a whole folder (add --json report.json to save)
#   truebit compare a.flac b.mp3     which copy is genuinely better?
#   truebit fix "D:\Music"           repair noise, make fakes honest, normalize loudness
#   truebit tags song.mp3            every tag; --set title="..." changes them for good
#   truebit repair song.wav          fix clipping, clicks and background noise
#   truebit normalize song.flac      set loudness to -14 LUFS (Spotify) or another target
#   truebit serve                    web API and upload page

import json
from pathlib import Path

import typer
from rich.box import ROUNDED
from rich.table import Table
from rich.text import Text

from truebit import __version__
from truebit.probe import AudioError
from truebit.report import analyze_file, find_audio_files, save_report, save_spectrogram
from truebit.ui import (
    BLUE,
    DIM,
    GREEN,
    RED,
    YELLOW,
    console,
    format_size,
    indented,
    run_with_spinner,
    tool_call,
    tool_result,
    welcome,
)

app = typer.Typer(help="TrueBit: is your audio really lossless? Check, fix and tag any audio file.",
                  add_completion=False, invoke_without_command=True)

VERDICT_COLORS = {"lossless": GREEN, "lossy": YELLOW, "fake_lossless": RED, "fake_bitrate": RED}


# `truebit` on its own opens TrueBit's interactive mode (like `claude` opens Claude Code)
@app.callback()
def main(context: typer.Context):
    if context.invoked_subcommand is None:
        from truebit.shell import start_shell

        welcome(__version__, Path.cwd())
        start_shell()


# Stops with a red message (used when a file can't be read)
def fail(message):
    tool_result(message, style=RED)
    raise typer.Exit(1)


# A bar chart of the high-frequency bands; the cliff shows as bars suddenly disappearing
def bands_chart(spectrum):
    chart = Text()
    for band in spectrum["bands"]:
        level = band["level_db"]
        chart.append(f"   {band['from_hz'] / 1000:>4.1f}–{band['to_hz'] / 1000:<4.1f} kHz  ", style=DIM)
        if level <= -200:
            chart.append("silent", style=RED)
        else:
            bar_length = max(0, int((level + 120) / 2.5))  # -120 dB = empty, -20 dB = full
            chart.append("█" * bar_length, style=BLUE)
            chart.append(f" {level:.0f} dB", style=DIM)
        if spectrum["cutoff_hz"] and band["from_hz"] <= spectrum["cutoff_hz"] < band["to_hz"]:
            chart.append("  ← cliff", style="bold " + RED)
        chart.append("\n")
    return chart


# Shows a length in seconds as minutes:seconds, e.g. 200.4 -> "3:20"
def minutes_and_seconds(seconds):
    whole_seconds = round(seconds)
    return f"{whole_seconds // 60}:{whole_seconds % 60:02d}"


# The "Really" line: what the sound is really worth
def real_quality_text(report):
    bitrate = report["bitrate"]
    text = bitrate["real_text"]
    if bitrate["inflated_times"] is not None and bitrate["inflated_times"] >= 1.4:
        text = text + f"   ← the label is {bitrate['inflated_times']:g}× too high"
    return text


# The codec in words, plus the container when it has a different name (e.g. "AAC ... in MP4")
def format_text(file_info):
    text = file_info["codec_name"]
    if file_info["container"].lower() not in text.lower():
        text = text + " in " + file_info["container_name"]
    if file_info["encoder"]:
        text = text + " · encoder " + file_info["encoder"]
    return text


# Title · Artist · Album (Year) · cover art
def tags_text(file_info):
    tags = file_info["tags"]
    parts = []
    for name in ["title", "artist", "album"]:
        if name in tags:
            parts.append(tags[name])
    if "date" in tags and len(parts) > 0:
        parts[-1] = parts[-1] + f" ({tags['date'][:4]})"
    if file_info["has_cover_art"]:
        parts.append("cover art")
    if len(parts) == 0:
        return "none"
    return " · ".join(parts)


# Prints one file's report as tool results
def print_report(report):
    file_info = report["file"]
    spectrum = report["spectrum"]
    loudness = report["loudness"]
    bitrate = report["bitrate"]
    color = VERDICT_COLORS.get(report["verdict"], "")

    tool_result(report["verdict_headline"], style="bold " + color)
    indented(report["verdict_detail"])
    console.print()

    # Step 1: the questions people ask: is it lossless, and what's the real bitrate?
    lossless_color = GREEN if report["lossless"]["is_lossless"] else color
    says = f"{bitrate['label_kbps']} kbps" if bitrate["label_kbps"] else "not given"
    if bitrate["mode"]:
        says = says + f" ({bitrate['mode']})"
    says = says + "   ← from the file's properties"
    stores = "?"
    if bitrate["stored_kbps"]:
        stores = (f"{bitrate['stored_kbps']} kbps   ← {format_size(file_info['file_size_bytes'])} over "
                  f"{minutes_and_seconds(file_info['duration_seconds'])}")
    question_rows = [
        ("Lossless?", report["lossless"]["answer"], lossless_color),
        ("Says", says, ""),
        ("Stores", stores, ""),
        ("Really", real_quality_text(report), color),
    ]
    for label, value, value_style in question_rows:
        console.print(Text(f"   {label:<12} ", style=DIM) + Text(value, style=value_style))
    console.print()

    # Step 2: everything else about the file
    depth = f" · {file_info['bit_depth']}-bit" if file_info["bit_depth"] else ""
    layout = file_info["channel_layout"] or f"{file_info['channels']} ch"
    if spectrum["cutoff_hz"]:
        cutoff = f"{spectrum['cutoff_hz'] / 1000:.2f} kHz (drop {spectrum['cutoff_drop_db']} dB)"
    else:
        cutoff = "none, sound reaches the top"
    rows = [
        ("File", f"{format_size(file_info['file_size_bytes'])} · {minutes_and_seconds(file_info['duration_seconds'])}"),
        ("Format", format_text(file_info)),
        ("Audio", f"{file_info['sample_rate_hz']:,} Hz · {layout}{depth}"),
        ("Tags", tags_text(file_info)),
        ("Cutoff", cutoff),
        ("Loudness", f"{loudness['integrated_lufs']} LUFS · true peak {loudness['true_peak_dbtp']} dBTP"
                     f" · range {loudness['loudness_range_lu']} LU"),
        ("Clean?", f"{loudness['clipped_samples']:,} clipped samples · noise floor "
                   f"{loudness['noise_floor_dbfs']} dB · crest {loudness['crest_factor_db']} dB"),
    ]
    for label, value in rows:
        console.print(Text(f"   {label:<12} ", style=DIM) + Text(value))
    console.print()
    console.print(bands_chart(spectrum), end="")


@app.command()
def check(file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Audio file to analyse."),
          save: bool = typer.Option(False, "--save", help="Save a JSON report and a spectrogram to ./truebit-reports.")):
    """Is this file really what it claims to be?"""
    tool_call("Check", file.name)
    try:
        report = run_with_spinner(analyze_file, file, detail=format_size(file.stat().st_size))
    except AudioError as error:
        fail(str(error))

    print_report(report)
    if save:
        console.print()
        tool_call("Saved", str(save_report(report, file)))
        image_path = save_spectrogram(file)
        if image_path is not None:
            tool_call("Saved", str(image_path))


# Codec names people know (FFmpeg calls WMA "wmav2", and WAV/AIFF "pcm_s16le"...)
SHORT_CODEC_NAMES = {"wmav1": "WMA", "wmav2": "WMA", "mp3float": "MP3"}


# A short name for the format, e.g. "MP3", "FLAC", "WAV", "AAC"
def short_format(file_info):
    codec = file_info["codec"]
    if codec.startswith("pcm_"):
        return file_info["container"].upper()
    return SHORT_CODEC_NAMES.get(codec, codec.upper())


# The "Really" column of the scan table, kept short
def short_real_quality(report):
    bitrate = report["bitrate"]
    if bitrate["real_kbps"] is not None:
        return bitrate["real_text"]
    if bitrate["real_text"] == "lossless":
        return "lossless"
    if report["spectrum"]["cutoff_hz"] is None:
        return "full band"
    return f"cut at {report['spectrum']['cutoff_hz'] / 1000:.1f} kHz"


# Analyses every file in a list, one by one (run inside the spinner)
def analyze_many(file_list):
    reports = {}
    for file_path in file_list:
        try:
            reports[str(file_path)] = analyze_file(file_path)
        except AudioError as error:
            reports[str(file_path)] = {"error": str(error)}
    return reports


@app.command()
def scan(folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder to scan."),
         json_out: Path = typer.Option(None, "--json", help="Save all reports to this JSON file.")):
    """Analyse every audio file in a folder (and its sub-folders)."""
    audio_files = find_audio_files(folder)
    tool_call("Scan", str(folder))
    if len(audio_files) == 0:
        tool_result("No audio files found.")
        return

    reports = run_with_spinner(analyze_many, audio_files, detail=f"{len(audio_files)} files")

    table = Table(box=ROUNDED, border_style=DIM, header_style="bold")
    table.add_column("File")
    table.add_column("Format")
    table.add_column("Says", justify="right")
    table.add_column("Stores", justify="right")
    table.add_column("Really", justify="right")
    table.add_column("Verdict")
    counts = {"lossless": 0, "fake": 0, "lossy": 0, "error": 0}
    for file_path in audio_files:
        report = reports[str(file_path)]
        if "error" in report:
            counts["error"] = counts["error"] + 1
            table.add_row(file_path.name, "—", "—", "—", "—", f"[{RED}]{report['error']}[/]")
            continue

        # Count each kind of file for the summary line
        if report["verdict"].startswith("fake"):
            counts["fake"] = counts["fake"] + 1
        elif report["verdict"] == "lossless":
            counts["lossless"] = counts["lossless"] + 1
        else:
            counts["lossy"] = counts["lossy"] + 1

        bitrate = report["bitrate"]
        color = VERDICT_COLORS.get(report["verdict"], "")
        table.add_row(file_path.name, short_format(report["file"]),
                      f"{bitrate['label_kbps'] or '?'}", f"{bitrate['stored_kbps'] or '?'}",
                      f"[{color}]{short_real_quality(report)}[/]",
                      f"[{color}]{report['verdict_headline']}[/]")
    console.print(table)
    summary = (f"{len(audio_files)} files · {counts['lossless']} genuine lossless · "
               f"{counts['fake']} fake · {counts['lossy']} lossy")
    if counts["error"] > 0:
        summary = summary + f" · {counts['error']} unreadable"
    tool_result(summary, style="bold")
    tool_result("Says and Stores are in kbps: what the properties say, and the file's size ÷ length.", style=DIM)
    if json_out is not None:
        json_out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        tool_call("Write", str(json_out))


# Shows a number nicely: whole numbers with commas (1,626,790), others with one decimal (-27.9)
def nice_number(value, with_sign=False):
    if float(value).is_integer():
        text = f"{int(value):+,}" if with_sign else f"{int(value):,}"
    else:
        text = f"{value:+.1f}" if with_sign else f"{value:.1f}"
    return text


# One row of a before/after table, green when the number improved
def add_change_row(table, label, before_value, after_value, unit, lower_is_better=True):
    if before_value is None or after_value is None:
        table.add_row(label, str(before_value), str(after_value), "")
        return
    improved = after_value < before_value if lower_is_better else after_value > before_value
    color = GREEN if improved else DIM
    change = round(after_value - before_value, 1)
    table.add_row(label, nice_number(before_value) + unit, f"[{color}]{nice_number(after_value)}{unit}[/]",
                  f"[{color}]{nice_number(change, with_sign=True)}{unit}[/]")


# An empty before/after table
def before_after_table():
    table = Table(box=ROUNDED, border_style=DIM, header_style="bold")
    table.add_column("")
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Change", justify="right")
    return table


@app.command()
def repair(file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Audio file to repair."),
           output: Path = typer.Option(None, "--output", "-o", help="Where to save (default: NAME.repaired + same format)."),
           output_format: str = typer.Option(None, "--format", help="Save as another format: mp3, m4a, flac, wav, ogg, opus..."),
           strength: str = typer.Option("medium", help="Noise reduction: light, medium or strong."),
           declip: bool = typer.Option(True, help="Rebuild clipped peaks."),
           declick: bool = typer.Option(True, help="Remove clicks and crackle."),
           denoise: bool = typer.Option(True, help="Reduce background hiss.")):
    """Repair clipping, clicks and background noise (saves a new file)."""
    from truebit.repair import repair_file

    tool_call("Repair", f"{file.name}, strength={strength}")
    try:
        output_path, before, after = run_with_spinner(repair_file, file, output, declick, declip,
                                                      denoise, strength, output_format,
                                                      detail=format_size(file.stat().st_size))
    except (AudioError, ValueError) as error:
        fail(str(error))

    table = before_after_table()
    add_change_row(table, "Clipped samples", before["clipped_samples"], after["clipped_samples"], "")
    add_change_row(table, "Background noise", before["noise_floor_dbfs"], after["noise_floor_dbfs"], " dB")
    add_change_row(table, "True peak", before["true_peak_dbtp"], after["true_peak_dbtp"], " dBTP")
    console.print(table)
    tool_call("Write", str(output_path))
    tool_result("Repair fixes damage. It cannot bring back frequencies an MP3 encoder deleted.", style=DIM)


@app.command()
def normalize(file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Audio file to normalize."),
              preset: str = typer.Option("spotify", help="spotify / youtube (-14), apple (-16), broadcast (-23)."),
              target: float = typer.Option(None, help="Custom target in LUFS, e.g. -12 (overrides preset)."),
              output: Path = typer.Option(None, "--output", "-o", help="Where to save."),
              output_format: str = typer.Option(None, "--format", help="Save as another format: mp3, m4a, flac, wav, ogg, opus...")):
    """Make a track exactly as loud as streaming services play it (two-pass EBU R128)."""
    from truebit.normalize import PRESETS, normalize_file

    if target is None:
        if preset not in PRESETS:
            fail("Presets: " + ", ".join(PRESETS))
        target = PRESETS[preset]

    tool_call("Normalize", f"{file.name}, target={target:g} LUFS")
    try:
        output_path, before, after = run_with_spinner(normalize_file, file, target, output, output_format,
                                                      detail=format_size(file.stat().st_size))
    except (AudioError, ValueError) as error:
        fail(str(error))

    table = before_after_table()
    change = after["integrated_lufs"] - before["integrated_lufs"]
    table.add_row("Loudness", f"{before['integrated_lufs']:g} LUFS", f"[{GREEN}]{after['integrated_lufs']:g} LUFS[/]",
                  f"{change:+.1f} dB")
    table.add_row("True peak", f"{before['true_peak_dbtp']:g} dBTP", f"{after['true_peak_dbtp']:g} dBTP", "")
    console.print(table)
    tool_call("Write", str(output_path))


# One row of the fix table: what was found, what was done, and the result
def fix_row(result):
    before = result["before"]
    after = result["after"]
    plan = result["plan"]

    # Step 1: what was wrong
    if len(plan["problems"]) > 0:
        found = f"[{YELLOW}]" + "\n".join(plan["problems"]) + "[/]"
    else:
        found = f"[{DIM}]nothing wrong[/]"

    # Step 2: what TrueBit did
    done = []
    if plan["declip"]:
        done.append("rebuilt clipped peaks")
    if plan["denoise"]:
        done.append(f"background noise {before['loudness']['noise_floor_dbfs']:g} → "
                    f"{after['loudness']['noise_floor_dbfs']:g} dB")
    if plan["honest_bitrate"] is not None:
        done.append(f"made honest: {short_format(after['file'])} {plan['honest_bitrate']} kbps")
    done.append(f"loudness {before['loudness']['integrated_lufs']:g} → {after['loudness']['integrated_lufs']:g} LUFS")

    # Step 3: the result
    color = VERDICT_COLORS.get(after["verdict"], "")
    size_change = (f"{format_size(before['file']['file_size_bytes'])} → "
                   f"{format_size(after['file']['file_size_bytes'])}")
    outcome = f"[{color}]{after['verdict_headline']}[/]\n{size_change}"
    return found, "\n".join(done), outcome


@app.command()
def fix(path: Path = typer.Argument(..., exists=True, help="An audio file, or a folder of them."),
        target: float = typer.Option(-14.0, help="Loudness target in LUFS (-14 = Spotify/YouTube, -16 = Apple)."),
        strength: str = typer.Option("light", help="Noise reduction when hiss is found: light, medium or strong."),
        output_format: str = typer.Option(None, "--format", help="Save everything as one format: mp3, m4a, flac..."),
        output_folder: Path = typer.Option(Path("truebit-fixed"), "--output-folder", "-o",
                                           help="Where the fixed files go (the originals are never changed).")):
    """Fix problem files: repair noise and clipping, make fakes honest, normalize loudness."""
    from truebit.fix import fix_many

    # Step 1: which files (a folder's files, but never the ones already in the output folder)
    if path.is_dir():
        output_root = output_folder.resolve()
        file_list = []
        for file_path in find_audio_files(path):
            if output_root not in file_path.resolve().parents:
                file_list.append(file_path)
    else:
        file_list = [path]
    tool_call("Fix", f"{path.name or path} ({len(file_list)} file{'s' if len(file_list) != 1 else ''})")
    if len(file_list) == 0:
        tool_result("No audio files found.")
        return

    # Step 2: fix them all
    results = run_with_spinner(fix_many, file_list, output_folder, target, strength, output_format,
                               detail=f"{len(file_list)} files")

    # Step 3: show what happened
    table = Table(box=ROUNDED, border_style=DIM, header_style="bold", show_lines=True)
    table.add_column("File")
    table.add_column("Found")
    table.add_column("Done")
    table.add_column("Result")
    fixed_count = 0
    for result in results:
        if "error" in result:
            table.add_row(result["input"].name, f"[{RED}]{result['error']}[/]", "—", "—")
            continue
        fixed_count = fixed_count + 1
        found, done, outcome = fix_row(result)
        table.add_row(result["input"].name + f"\n[{DIM}]→ {result['output'].name}[/]", found, done, outcome)
    console.print(table)
    tool_call("Saved", f"{fixed_count} file{'s' if fixed_count != 1 else ''} in {output_folder}")
    tool_result("Tags and cover art are kept. Nothing can bring back sound a lossy encoder deleted, "
                "so fixed fakes are honest and smaller, not better.", style=DIM)


# Turns ["title=My Song", "year=2024"] into {"title": "My Song", "year": "2024"}
def parse_set_values(set_values):
    result = {}
    for item in set_values or []:
        if "=" not in item:
            fail(f'"{item}" needs a name and a value, like --set title="My Song"')
        name, value = item.split("=", 1)
        result[name.strip()] = value.strip()
    return result


# "image/jpeg, 45 KB" for the cover art, or "none"
def cover_text(cover):
    if cover is None:
        return "none"
    kind = cover["mime"].split("/")[-1].upper().replace("JPEG", "JPG")
    if cover["bytes"] < 1024:
        return f"{kind} picture, {cover['bytes']} bytes"
    return f"{kind} picture, {format_size(cover['bytes'])}"


# Shows every tag of one file
def show_file_tags(file_path):
    from truebit.tags import read_all_tags

    info = read_all_tags(file_path)
    tool_result(f"{len(info['tags'])} tags · cover art: {cover_text(info['cover'])} · stored as {info['family']}")
    for name, value in info["tags"]:
        console.print(Text(f"   {name:<14} ", style=DIM) + Text(short_value(value)))


# Long values (like lyrics) as their first line, e.g. "Y'all throwin'... (48 lines)"
def short_value(value):
    lines = value.strip().splitlines()
    if len(lines) == 0:
        return ""
    text = lines[0]
    if len(text) > 90:
        text = text[:90] + "…"
    if len(lines) > 1:
        text = text + f"  ({len(lines)} lines)"
    return text


# Shows title / artist / album... for every file in a folder
def show_folder_tags(file_list):
    from truebit.tags import read_all_tags

    table = Table(box=ROUNDED, border_style=DIM, header_style="bold")
    for column in ["File", "Title", "Artist", "Album", "Year", "Track", "Cover"]:
        table.add_column(column)
    for file_path in file_list:
        try:
            info = read_all_tags(file_path)
        except Exception as error:  # a file mutagen can't read shouldn't stop the list
            table.add_row(file_path.name, f"[{RED}]{error}[/]", "", "", "", "", "")
            continue
        values = dict(info["tags"])
        table.add_row(file_path.name, values.get("title", ""), values.get("artist", ""), values.get("album", ""),
                      values.get("year", ""), values.get("track", ""), "✓" if info["cover"] else "")
    console.print(table)


@app.command()
def tags(path: Path = typer.Argument(..., exists=True, help="An audio file, or a folder of them."),
         set_values: list[str] = typer.Option(None, "--set", help='Set a tag, e.g. --set title="My Song" (repeat for more).'),
         remove: list[str] = typer.Option(None, "--remove", help="Remove a tag, e.g. --remove comment."),
         clear: bool = typer.Option(False, "--clear", help="Remove every tag and the cover art."),
         cover: Path = typer.Option(None, "--cover", exists=True, dir_okay=False, help="New cover art (.jpg or .png)."),
         remove_cover: bool = typer.Option(False, "--remove-cover", help="Take the cover art out."),
         save_cover_to: Path = typer.Option(None, "--save-cover", help="Save the cover art as a picture file."),
         output: Path = typer.Option(None, "--output", "-o", help="Change a copy instead of the original."),
         yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask before changing files.")):
    """See every tag (title, artist, album, cover art...) and change them for good."""
    from truebit.tags import TagError, change_tags, read_all_tags, save_cover

    # Step 1: which files
    if path.is_dir():
        file_list = find_audio_files(path)
    else:
        file_list = [path]
    if len(file_list) == 0:
        tool_call("Tags", str(path))
        tool_result("No audio files found.")
        return

    new_values = parse_set_values(set_values)
    wants_changes = len(new_values) > 0 or len(remove or []) > 0 or clear or cover is not None or remove_cover

    # Step 2: just looking
    if not wants_changes:
        tool_call("Tags", path.name or str(path))
        try:
            if path.is_dir():
                show_folder_tags(file_list)
            else:
                show_file_tags(path)
                if save_cover_to is not None:
                    saved_path = save_cover(path, save_cover_to)
                    if saved_path is None:
                        tool_result("There's no cover art to save.", style=YELLOW)
                    else:
                        tool_call("Saved", str(saved_path))
        except TagError as error:
            fail(str(error))
        return

    # Step 3: changing. Unless it's a copy, ask first: this changes the files for good.
    if output is not None and path.is_dir():
        fail("--output works with one file. For a folder, the files themselves are changed.")
    if output is None and not yes:
        count = f"{len(file_list)} file{'s' if len(file_list) != 1 else ''}"
        if not typer.confirm(f"Change the tags of {count} permanently? (The sound itself isn't touched.)"):
            tool_result("Nothing was changed.", style=DIM)
            return

    tool_call("Tags", f"{path.name or path} ({len(file_list)} file{'s' if len(file_list) != 1 else ''})")
    changed_count = 0
    for file_path in file_list:
        try:
            before = dict(read_all_tags(file_path)["tags"])
            changed_path = change_tags(file_path, new_values, remove, clear, cover, remove_cover, output)
            after_info = read_all_tags(changed_path)
            changed_count = changed_count + 1
        except (TagError, OSError) as error:
            tool_result(f"{file_path.name}: {error}", style=RED)
            continue

        # One file: show exactly what changed, before and after
        if len(file_list) == 1:
            after = dict(after_info["tags"])
            table = Table(box=ROUNDED, border_style=DIM, header_style="bold")
            table.add_column("Tag")
            table.add_column("Before")
            table.add_column("After")
            changed_names = sorted(set(before) | set(after))
            for name in changed_names:
                if before.get(name) != after.get(name):
                    table.add_row(name, before.get(name, f"[{DIM}]—[/]"), after.get(name, f"[{DIM}]removed[/]"))
            if cover is not None or remove_cover or clear:
                table.add_row("cover art", "", cover_text(after_info["cover"]))
            console.print(table)
            if output is not None:
                tool_call("Saved", str(changed_path))

    tool_result(f"Changed {changed_count} of {len(file_list)} file{'s' if len(file_list) != 1 else ''}. "
                "Only the tags were rewritten: the audio is exactly the same.", style=GREEN)


# One cell of the compare table
def compare_cell(report, kind):
    file_info = report["file"]
    if kind == "verdict":
        color = VERDICT_COLORS.get(report["verdict"], "")
        return f"[{color}]{report['verdict_headline']}[/]"
    if kind == "format":
        return f"{short_format(file_info)} · {file_info['bitrate_kbps'] or '?'} kbps"
    if kind == "cutoff":
        cutoff = report["spectrum"]["cutoff_hz"]
        if cutoff:
            return f"{cutoff / 1000:.1f} kHz"
        return "full band"
    if kind == "loudness":
        return f"{report['loudness']['integrated_lufs']} LUFS"
    if kind == "clipping":
        return str(report["loudness"]["clipped_samples"])
    return ""


@app.command()
def compare(first: Path = typer.Argument(..., exists=True, dir_okay=False),
            second: Path = typer.Argument(..., exists=True, dir_okay=False),
            json_out: Path = typer.Option(None, "--json", help="Save both reports to a JSON file.")):
    """Which of two copies of a song is genuinely better?"""
    from truebit.compare import compare_files

    tool_call("Compare", f"{first.name}, {second.name}")
    try:
        result = run_with_spinner(compare_files, first, second, detail="2 files")
    except AudioError as error:
        fail(str(error))

    table = Table(box=ROUNDED, border_style=DIM, header_style="bold")
    table.add_column("")
    for side in ["first", "second"]:
        name = result[side]["file"]
        if name == result["winner"]:
            table.add_column(f"[{GREEN}]{name} ✓[/]", justify="right")
        else:
            table.add_column(name, justify="right")
    rows = [("Verdict", "verdict"), ("Format", "format"), ("Real cutoff", "cutoff"),
            ("Loudness", "loudness"), ("Clipped samples", "clipping")]
    for label, kind in rows:
        table.add_row(label, compare_cell(result["first"]["report"], kind),
                      compare_cell(result["second"]["report"], kind))
    console.print(table)

    if result["winner"] is None:
        tool_result(result["reason"], style=YELLOW)
    else:
        tool_result(f"Keep {result['winner']}. {result['reason']}", style="bold " + GREEN)
    if result["warning"]:
        tool_result(result["warning"], style=YELLOW)
    if json_out is not None:
        json_out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        tool_call("Write", str(json_out))


@app.command()
def serve(host: str = typer.Option("127.0.0.1", help="Use 0.0.0.0 to allow other devices."),
          port: int = typer.Option(8000)):
    """Start the web API and upload page (5 analyses per IP per day)."""
    import uvicorn

    from truebit.api import create_app

    tool_call("Serve", f"http://{host}:{port}")
    tool_result(f"Upload page: http://{host}:{port}   ·   API docs: http://{host}:{port}/docs", style=DIM)
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command()
def version():
    """Show the version."""
    console.print(f"truebit {__version__}")
