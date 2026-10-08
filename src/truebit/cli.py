# The `truebit` command, styled like Claude Code.
#
#   truebit                          welcome screen
#   truebit check song.flac          real or fake? verdict, spectrum bands, loudness
#   truebit scan "D:\Music"          a whole folder (add --json report.json to save)
#   truebit compare a.flac b.mp3     which copy is genuinely better?
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
from truebit.ui import (BLUE, DIM, GREEN, RED, YELLOW, console, format_size,
                        indented, run_with_spinner, tool_call, tool_result, welcome)

app = typer.Typer(help="TrueBit: catch fake lossless and fake 320 kbps audio.",
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


# Prints one file's report as tool results
def print_report(report):
    file_info = report["file"]
    spectrum = report["spectrum"]
    loudness = report["loudness"]
    color = VERDICT_COLORS.get(report["verdict"], "")

    tool_result(report["verdict_headline"], style="bold " + color)
    indented(report["verdict_detail"])
    console.print()

    bitrate = f"{file_info['bitrate_kbps']} kbps" if file_info["bitrate_kbps"] else "?"
    depth = f" · {file_info['bit_depth']}-bit" if file_info["bit_depth"] else ""
    if spectrum["cutoff_hz"]:
        cutoff = f"{spectrum['cutoff_hz'] / 1000:.2f} kHz (drop {spectrum['cutoff_drop_db']} dB)"
    else:
        cutoff = "none, sound reaches the top"
    rows = [
        ("Format", f"{file_info['codec'].upper()} · {bitrate}"),
        ("Sample rate", f"{file_info['sample_rate_hz']:,} Hz · {file_info['channels']} ch{depth}"),
        ("Duration", f"{file_info['duration_seconds']:.1f} s"),
        ("Cutoff", cutoff),
        ("Loudness", f"{loudness['integrated_lufs']} LUFS · true peak {loudness['true_peak_dbtp']} dBTP"),
        ("Clipping", f"{loudness['clipped_samples']} clipped samples · crest {loudness['crest_factor_db']} dB"),
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
    table.add_column("Cutoff", justify="right")
    table.add_column("Verdict")
    fake_count = 0
    for file_path in audio_files:
        report = reports[str(file_path)]
        if "error" in report:
            table.add_row(file_path.name, "—", "—", f"[{RED}]{report['error']}[/]")
            continue
        if report["verdict"].startswith("fake"):
            fake_count = fake_count + 1
        cutoff = report["spectrum"]["cutoff_hz"]
        color = VERDICT_COLORS.get(report["verdict"], "")
        table.add_row(file_path.name, report["file"]["codec"].upper(),
                      f"{cutoff / 1000:.1f} kHz" if cutoff else "full",
                      f"[{color}]{report['verdict_headline']}[/]")
    console.print(table)
    tool_result(f"{len(audio_files)} files · {fake_count} fake", style="bold")
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
           output: Path = typer.Option(None, "--output", "-o", help="Where to save (default: NAME.repaired.flac)."),
           strength: str = typer.Option("medium", help="Noise reduction: light, medium or strong."),
           declip: bool = typer.Option(True, help="Rebuild clipped peaks."),
           declick: bool = typer.Option(True, help="Remove clicks and crackle."),
           denoise: bool = typer.Option(True, help="Reduce background hiss.")):
    """Repair clipping, clicks and background noise (saves a new file)."""
    from truebit.repair import repair_file

    tool_call("Repair", f"{file.name}, strength={strength}")
    try:
        output_path, before, after = run_with_spinner(repair_file, file, output, declick, declip,
                                                      denoise, strength,
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
              output: Path = typer.Option(None, "--output", "-o", help="Where to save.")):
    """Make a track exactly as loud as streaming services play it (two-pass EBU R128)."""
    from truebit.normalize import PRESETS, normalize_file

    if target is None:
        if preset not in PRESETS:
            fail("Presets: " + ", ".join(PRESETS))
        target = PRESETS[preset]

    tool_call("Normalize", f"{file.name}, target={target:g} LUFS")
    try:
        output_path, before, after = run_with_spinner(normalize_file, file, target, output,
                                                      detail=format_size(file.stat().st_size))
    except AudioError as error:
        fail(str(error))

    table = before_after_table()
    change = after["integrated_lufs"] - before["integrated_lufs"]
    table.add_row("Loudness", f"{before['integrated_lufs']:g} LUFS", f"[{GREEN}]{after['integrated_lufs']:g} LUFS[/]",
                  f"{change:+.1f} dB")
    table.add_row("True peak", f"{before['true_peak_dbtp']:g} dBTP", f"{after['true_peak_dbtp']:g} dBTP", "")
    console.print(table)
    tool_call("Write", str(output_path))


# One cell of the compare table
def compare_cell(report, kind):
    file_info = report["file"]
    if kind == "verdict":
        color = VERDICT_COLORS.get(report["verdict"], "")
        return f"[{color}]{report['verdict_headline']}[/]"
    if kind == "format":
        return f"{file_info['codec'].upper()} · {file_info['bitrate_kbps'] or '?'} kbps"
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
