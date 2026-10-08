# The `truebit` command.
#
#   truebit check song.flac          analyse one file: verdict, spectrum bands, loudness
#   truebit scan "D:\Music"          analyse a whole folder and show a table
#   truebit scan "D:\Music" --json report.json

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from truebit import __version__
from truebit.probe import AudioError
from truebit.report import analyze_file, find_audio_files, save_report, save_spectrogram

app = typer.Typer(help="TrueBit: catch fake lossless and fake 320 kbps audio.", add_completion=False)
console = Console()

# Shown while the analysis runs, like Claude Code's spinner words
SPINNER_VERBS = [
    "Untangling waveforms", "Interrogating the Nyquist", "Sniffing for brickwalls",
    "Counting lost harmonics", "Bribing the FFT", "Listening very carefully",
    "Measuring the loudness war", "Squinting at 16 kHz", "Asking the encoder nicely",
]

VERDICT_STYLES = {
    "lossless": "bold green",
    "lossy": "bold yellow",
    "fake_lossless": "bold red",
    "fake_bitrate": "bold red",
}


# Runs the analysis in the background while the spinner shows changing words
def analyze_with_spinner(file_path):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(analyze_file, file_path)
        with console.status(random.choice(SPINNER_VERBS) + "…", spinner="dots") as status:
            while not future.done():
                time.sleep(0.6)
                status.update(random.choice(SPINNER_VERBS) + "…")
        return future.result()


# A bar chart of the high-frequency bands; the cliff shows as bars suddenly disappearing
def bands_chart(spectrum):
    text = Text()
    for band in spectrum["bands"]:
        level = band["level_db"]
        label = f"{band['from_hz'] / 1000:>5.1f}-{band['to_hz'] / 1000:<5.1f} kHz "
        bar_length = max(0, int((level + 120) / 2.5))  # -120 dB = empty, -20 dB = full
        text.append(label, style="dim")
        if level <= -200:
            text.append("silent", style="red")
        else:
            text.append("█" * bar_length, style="cyan")
            text.append(f" {level:.0f} dB", style="dim")
        if spectrum["cutoff_hz"] and band["from_hz"] <= spectrum["cutoff_hz"] < band["to_hz"]:
            text.append("  ← cliff", style="bold red")
        text.append("\n")
    return text


# Prints the full result for one file
def print_report(report, file_path):
    file_info = report["file"]
    spectrum = report["spectrum"]
    loudness = report["loudness"]

    style = VERDICT_STYLES.get(report["verdict"], "bold")
    console.print(Panel(Text(report["verdict_headline"], style=style) + Text("\n\n" + report["verdict_detail"]),
                        title=f"[bold]{Path(file_path).name}[/]", border_style=style.split()[-1], padding=(1, 2)))

    details = Table(show_header=False, box=None, padding=(0, 2))
    details.add_column(style="dim")
    details.add_column()
    bitrate = f"{file_info['bitrate_kbps']} kbps" if file_info["bitrate_kbps"] else "—"
    details.add_row("Format", f"{file_info['codec'].upper()} in {file_info['container']} · {bitrate}")
    details.add_row("Sample rate", f"{file_info['sample_rate_hz']:,} Hz · {file_info['channels']} channels"
                    + (f" · {file_info['bit_depth']}-bit" if file_info["bit_depth"] else ""))
    details.add_row("Duration", f"{file_info['duration_seconds']:.1f} s")
    cutoff = f"{spectrum['cutoff_hz'] / 1000:.2f} kHz (drop {spectrum['cutoff_drop_db']} dB)" if spectrum["cutoff_hz"] else "none (full band)"
    details.add_row("Cutoff", cutoff)
    details.add_row("Loudness", f"{loudness['integrated_lufs']} LUFS · true peak {loudness['true_peak_dbtp']} dBTP"
                    f" · crest {loudness['crest_factor_db']} dB · {loudness['clipped_samples']} clipped samples")
    console.print(details)
    console.print()
    console.print(bands_chart(spectrum))


@app.command()
def check(file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Audio file to analyse."),
          spectrogram: bool = typer.Option(True, help="Also save a spectrogram PNG.")):
    """Analyse one audio file."""
    try:
        report = analyze_with_spinner(file)
    except AudioError as error:
        console.print(f"[red]{error}[/]")
        raise typer.Exit(1)

    print_report(report, file)
    json_path = save_report(report, file)
    console.print(f"[dim]Report saved: {json_path}[/]")
    if spectrogram:
        image_path = save_spectrogram(file)
        if image_path is not None:
            console.print(f"[dim]Spectrogram saved: {image_path}[/]")


@app.command()
def scan(folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder to scan."),
         json_out: Path = typer.Option(None, "--json", help="Save all reports to this JSON file.")):
    """Analyse every audio file in a folder (and its sub-folders)."""
    audio_files = find_audio_files(folder)
    if len(audio_files) == 0:
        console.print("No audio files found.")
        return

    table = Table(header_style="bold cyan")
    table.add_column("File")
    table.add_column("Format")
    table.add_column("Cutoff", justify="right")
    table.add_column("Verdict")

    all_reports = {}
    fake_count = 0
    start_time = time.perf_counter()
    with console.status("Scanning…", spinner="dots") as status:
        for number, file_path in enumerate(audio_files, start=1):
            status.update(f"{random.choice(SPINNER_VERBS)}… ({number}/{len(audio_files)}) {file_path.name}")
            try:
                report = analyze_file(file_path)
            except AudioError as error:
                table.add_row(file_path.name, "—", "—", f"[red]error: {error}[/]")
                continue
            all_reports[str(file_path)] = report
            if report["verdict"].startswith("fake"):
                fake_count = fake_count + 1
            cutoff = report["spectrum"]["cutoff_hz"]
            style = VERDICT_STYLES.get(report["verdict"], "")
            table.add_row(file_path.name, report["file"]["codec"].upper(),
                          f"{cutoff / 1000:.1f} kHz" if cutoff else "full",
                          f"[{style}]{report['verdict_headline']}[/]")

    seconds = time.perf_counter() - start_time
    console.print(table)
    console.print(f"{len(audio_files)} files in {seconds:.1f} s · [bold red]{fake_count} fake[/]")
    if json_out is not None:
        json_out.write_text(json.dumps(all_reports, indent=2), encoding="utf-8")
        console.print(f"[dim]Saved {json_out}[/]")


@app.command()
def serve(host: str = typer.Option("127.0.0.1", help="Use 0.0.0.0 to allow other devices."),
          port: int = typer.Option(8000)):
    """Start the web API and upload page (5 analyses per IP per day)."""
    import uvicorn

    from truebit.api import create_app

    console.print(f"TrueBit API on http://{host}:{port}  (docs: http://{host}:{port}/docs)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command()
def version():
    """Show the version."""
    console.print("truebit " + __version__)
