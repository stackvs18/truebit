# TrueBit's terminal look: macOS blue, an animated equalizer, and its own symbols.
#
#   ▂▅▇▃ Sniffing for brickwalls… (12s · 4.2 MB · ctrl+c to stop)     <- animated "thinking" line
#
#   ◆ Check  song.flac                                                 <- an action
#   ╰─ FAKE LOSSLESS: upscaled from ~128 kbps                          <- its result
#
# The four equalizer bars bounce like audio levels, a light band shimmers across the verb,
# the verb changes every 2 seconds, and the timer counts up.

import math
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console
from rich.live import Live
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

BLUE = "#0A84FF"  # macOS system blue (dark mode)
LIGHT_BLUE = "#64D2FF"  # macOS cyan, used for the shimmer and the logo gradient
GREEN = "#30D158"  # macOS green
RED = "#FF453A"  # macOS red
YELLOW = "#FFD60A"  # macOS yellow
DIM = "#8E8E93"  # macOS secondary grey

BAR_LEVELS = "▁▂▃▄▅▆▇█"
SECONDS_PER_VERB = 2.0

VERBS = [
    "Sniffing for brickwalls", "Interrogating the Nyquist", "Untangling waveforms",
    "Counting lost harmonics", "Bribing the FFT", "Squinting at 16 kHz", "Listening very carefully",
    "Measuring the loudness war", "Asking the encoder nicely", "Welching the spectrum",
    "Chasing the cliff", "Consulting the spectrogram", "Herding decibels", "Unmuddling the mids",
    "Polishing peaks", "Hushing the hiss", "Smoothing the crackle", "Tuning the tweeters",
    "Weighing every bit", "Following the frequencies",
]

# The TRUEBIT logo, drawn with block characters (two rows)
LOGO_TOP = "▀█▀ █▀█ █ █ █▀▀ █▄▄ █ ▀█▀"
LOGO_BOTTOM = " █  █▀▄ █▄█ ██▄ █▄█ █  █ "

# When the output goes to a file or a pipe (truebit scan D:\Music > report.txt), Windows uses an
# old text encoding that has no ◆ or █ and would crash. Always write UTF-8 instead.
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

console = Console(highlight=False)


# "8s", "1m 05s"
def format_elapsed(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


# "4.2 MB"
def format_size(byte_count):
    if byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.0f} KB"
    return f"{byte_count / 1024 / 1024:.1f} MB"


# Picks a new verb that isn't the same as the last one
def next_verb(previous_verb):
    verb = random.choice(VERBS)
    while verb == previous_verb:
        verb = random.choice(VERBS)
    return verb


# Four equalizer bars. Each bar bounces on its own sine wave, so they move like audio levels.
def equalizer_frame(elapsed):
    bars = ""
    for bar_number in range(4):
        wave = math.sin(elapsed * 9 + bar_number * 1.7) * 0.5 + math.sin(elapsed * 5.3 + bar_number) * 0.5
        height = int((wave + 1) / 2 * (len(BAR_LEVELS) - 1))
        bars = bars + BAR_LEVELS[height]
    return bars


# One frame of the thinking line
def thinking_line(verb, started_at, detail):
    elapsed = time.monotonic() - started_at

    line = Text()
    line.append(equalizer_frame(elapsed) + " ", style=BLUE)

    # The shimmer: a light band that sweeps across the verb, left to right
    word = verb + "…"
    band_position = int(elapsed * 14) % (len(word) + 8) - 4
    for position in range(len(word)):
        if abs(position - band_position) <= 1:
            line.append(word[position], style="bold " + LIGHT_BLUE)
        else:
            line.append(word[position], style=BLUE)

    extras = [format_elapsed(elapsed)]
    if detail:
        extras.append(detail)
    extras.append("ctrl+c to stop")
    line.append(" (" + " · ".join(extras) + ")", style=DIM)
    return line


# Runs job(*arguments) in the background while the animated thinking line plays.
# Returns the job's result (or raises its error).
def run_with_spinner(job, *arguments, detail=""):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(job, *arguments)
        started_at = time.monotonic()
        verb = next_verb(None)
        verb_changed_at = started_at

        with Live(thinking_line(verb, started_at, detail), console=console,
                  refresh_per_second=20, transient=True) as live:
            while not future.done():
                if time.monotonic() - verb_changed_at >= SECONDS_PER_VERB:
                    verb = next_verb(verb)
                    verb_changed_at = time.monotonic()
                live.update(thinking_line(verb, started_at, detail))
                time.sleep(0.05)

        took = format_elapsed(time.monotonic() - started_at)
        result = future.result()
        console.print(Text("▂▄▆█ ", style=BLUE) + Text(f"Done in {took}", style=DIM))
        return result


# "◆ Check  song.flac"
def tool_call(name, argument, ok=True):
    line = Text()
    line.append("◆ ", style=BLUE if ok else RED)
    line.append(name, style="bold")
    line.append("  " + argument, style=DIM)
    console.print(line)


# "╰─ text" under an action. A two-column grid keeps long, wrapped text indented.
def tool_result(text, style=""):
    grid = Table.grid()
    grid.add_column(width=3, no_wrap=True)
    grid.add_column()
    grid.add_row(Text("╰─ ", style=DIM), Text(str(text), style=style))
    console.print(grid)


# Indented text (used for longer explanations under a result)
def indented(text, style=DIM):
    console.print(Padding(Text(str(text), style=style), (0, 0, 0, 3)))


# The logo, coloured from blue to light blue, left to right
def logo_line(row_text):
    line = Text()
    for position in range(len(row_text)):
        if position < len(row_text) / 2:
            line.append(row_text[position], style="bold " + BLUE)
        else:
            line.append(row_text[position], style="bold " + LIGHT_BLUE)
    return line


# The start screen shown when TrueBit opens
def welcome(version, folder):
    console.print()
    console.print(Text("  ") + logo_line(LOGO_TOP))
    console.print(Text("  ") + logo_line(LOGO_BOTTOM))
    console.print()
    console.print(Text(f"  v{version} · is your FLAC really lossless?", style=DIM))
    console.print()

    commands = [
        ("check FILE", "lossless? real bitrate?"),
        ("scan FOLDER", "a whole library"),
        ("compare A B", "which copy is better"),
        ("fix PATH", "clean up noisy and fake files"),
        ("tags PATH", "see and change tags, cover art"),
        ("repair FILE", "fix clipping, clicks, hiss"),
        ("normalize FILE", "-14 LUFS like Spotify"),
        ("help · exit", ""),
    ]
    for command, meaning in commands:
        console.print(Text(f"  {command:<18}", style=BLUE) + Text(meaning, style=DIM))
    console.print()
    console.print(Text("  Tip: drag a file or folder into this window and press Enter.", style=DIM))
    console.print(Text(f"  {folder}", style=DIM))
    console.print()
