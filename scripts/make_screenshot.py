# Makes docs/check.svg: what `truebit check` looks like in a terminal (for the README).
# Run from the project folder:  uv run python scripts/make_screenshot.py tests/audio/fake_from_128.flac

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.text import Text

import truebit
import truebit.cli as cli
import truebit.ui as ui
from truebit.report import analyze_file

audio_file = Path(sys.argv[1])

# Step 1: record everything printed, instead of only showing it
ui.console = Console(record=True, width=92, force_terminal=True, color_system="truecolor")
cli.console = ui.console

# Step 2: print what a real run looks like (with one frame of the animated spinner)
ui.welcome(truebit.__version__, Path("D:/Music"))
ui.console.print(Text("truebit ", style="bold " + ui.BLUE) + Text("› ", style=ui.DIM) + Text("check " + audio_file.name + " --save"))
ui.console.print()
ui.tool_call("Check", audio_file.name)
pretend_start = time.monotonic() - 12.4
ui.console.print(ui.thinking_line("Sniffing for brickwalls", pretend_start, "1.1 MB"))
ui.console.print(Text("▂▄▆█ ", style=ui.BLUE) + Text("Done in 1s", style=ui.DIM))
cli.print_report(analyze_file(audio_file))
ui.console.print()
ui.tool_call("Saved", "truebit-reports/" + audio_file.stem + ".truebit.json")
ui.tool_call("Saved", "truebit-reports/" + audio_file.stem + ".spectrogram.png")

# Step 3: save as an SVG picture
Path("docs").mkdir(exist_ok=True)
ui.console.save_svg("docs/check.svg", title="truebit")
print("saved docs/check.svg")
