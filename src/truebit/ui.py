# The Claude Code look for TrueBit's terminal output.
#
#   ✻ Sniffing for brickwalls… (12s · 4.2 MB · ctrl+c to stop)     <- animated "thinking" line
#
#   ⏺ Check(fake_from_128.flac)                                     <- a tool call
#     ⎿  FAKE LOSSLESS: upscaled from ~128 kbps                      <- its result
#
# The star changes shape every 0.1 s (· ✢ ✳ ✶ ✻ ✽ and back), a bright band shimmers across
# the verb, the verb itself changes every 2 seconds, and the timer counts up.

import random
import time
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

CLAUDE_ORANGE = "#D77757"
SHIMMER = "#F4C6B3"
GREEN = "#7BC67E"
RED = "#E8735A"
YELLOW = "#E5C07B"
DIM = "#8A8A8A"

STAR_FRAMES = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]
SECONDS_PER_VERB = 2.0

VERBS = [
    "Pollinating", "Sniffing for brickwalls", "Interrogating the Nyquist", "Untangling waveforms",
    "Counting lost harmonics", "Bribing the FFT", "Squinting at 16 kHz", "Listening very carefully",
    "Measuring the loudness war", "Asking the encoder nicely", "Welching the spectrum",
    "Chasing the cliff", "Decoding vibes", "Consulting the spectrogram", "Herding decibels",
    "Unmuddling the mids", "Polishing peaks", "Hushing the hiss", "Smoothing the crackle",
]

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


# One frame of the thinking line
def thinking_line(verb, started_at, detail):
    elapsed = time.monotonic() - started_at
    frame = STAR_FRAMES[int(elapsed * 10) % len(STAR_FRAMES)]

    line = Text()
    line.append(frame + " ", style=CLAUDE_ORANGE)

    # The shimmer: a bright band that sweeps across the verb, left to right
    word = verb + "…"
    band_position = int(elapsed * 14) % (len(word) + 8) - 4
    for position in range(len(word)):
        if abs(position - band_position) <= 1:
            line.append(word[position], style="bold " + SHIMMER)
        else:
            line.append(word[position], style=CLAUDE_ORANGE)

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
        console.print(Text("✻ ", style=CLAUDE_ORANGE) + Text(f"Done in {took}", style=DIM))
        return result


# "⏺ Check(song.flac)"
def tool_call(name, argument, ok=True):
    line = Text()
    line.append("⏺ ", style=GREEN if ok else RED)
    line.append(name, style="bold")
    line.append("(" + argument + ")")
    console.print(line)


# "  ⎿  text" under a tool call. A two-column grid keeps long, wrapped text indented.
def tool_result(text, style=""):
    grid = Table.grid()
    grid.add_column(width=5, no_wrap=True)
    grid.add_column()
    grid.add_row(Text("  ⎿  ", style=DIM), Text(str(text), style=style))
    console.print(grid)


# Indented text (used for longer explanations under a result)
def indented(text, style=DIM):
    console.print(Padding(Text(str(text), style=style), (0, 0, 0, 5)))


# The welcome box shown by `truebit` with no command
def welcome(version, folder):
    body = Text()
    body.append("✻ ", style=CLAUDE_ORANGE)
    body.append("Welcome to TrueBit!", style="bold")
    body.append(f"  v{version}\n\n", style=DIM)
    body.append("  /help for help, or try:\n\n", style=DIM)
    commands = [
        ("truebit check song.flac", "real or fake?"),
        ("truebit scan D:\\Music", "a whole library"),
        ("truebit compare a.flac b.mp3", "which copy is better"),
        ("truebit repair old.wav", "fix clipping, clicks, hiss"),
        ("truebit normalize song.flac", "-14 LUFS like Spotify"),
        ("truebit serve", "web upload page"),
    ]
    for command, meaning in commands:
        body.append(f"  {command:<32}", style=CLAUDE_ORANGE)
        body.append(meaning + "\n", style=DIM)
    body.append(f"\n  cwd: {folder}", style=DIM)
    console.print(Panel(body, border_style=CLAUDE_ORANGE, padding=(1, 2), expand=False))
