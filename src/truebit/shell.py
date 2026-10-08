# Interactive mode: typing `truebit` on its own opens TrueBit and keeps it open,
# like `claude` opens Claude Code. You type commands at its own prompt until `exit`.
#
#   truebit › check "C:\Music\song.flac"
#   truebit › C:\Music\song.flac              (just a file path = check it)
#   truebit › C:\Music                        (just a folder path = scan it)
#   truebit › help
#   truebit › exit

from pathlib import Path

import click
import typer
from rich.text import Text

from truebit.ui import BLUE, DIM, RED, console

COMMANDS = ["check", "scan", "compare", "repair", "normalize", "serve", "version"]
EXIT_WORDS = ["exit", "quit", "q", ":q"]

HELP_ROWS = [
    ("check FILE", "Is this file really what it claims? (add --save for JSON + spectrogram)"),
    ("scan FOLDER", "Check every audio file in a folder (--json report.json to save)"),
    ("compare A B", "Which of two copies is genuinely better"),
    ("repair FILE", "Fix clipping, clicks and hiss (--strength light/medium/strong)"),
    ("normalize FILE", "Set loudness to -14 LUFS (--preset apple / broadcast, --target -12)"),
    ("serve", "Start the web upload page (ctrl+c to stop)"),
    ("FILE or FOLDER", "Just paste or drag a path: a file is checked, a folder is scanned"),
    ("clear", "Clear the screen"),
    ("exit", "Leave TrueBit"),
]


# Splits a typed line into words, keeping "quoted paths with spaces" together.
# (Windows paths contain backslashes, so we can't use Python's shlex here.)
def split_command(line):
    words = []
    current = ""
    inside_quotes = False
    for character in line:
        if character == '"' or character == "'":
            inside_quotes = not inside_quotes
        elif character == " " and not inside_quotes:
            if current != "":
                words.append(current)
                current = ""
        else:
            current = current + character
    if current != "":
        words.append(current)
    return words


# Prints the list of commands
def show_help():
    console.print()
    for command, meaning in HELP_ROWS:
        console.print(Text(f"  {command:<18}", style=BLUE) + Text(meaning, style=DIM))
    console.print()


# Turns what the user typed into the words for a TrueBit command (or None if unknown)
def to_command_words(words):
    # "truebit check x" typed inside TrueBit: ignore the extra "truebit"
    if len(words) > 0 and words[0].lower() == "truebit":
        words = words[1:]
    if len(words) == 0:
        return None

    first_word = words[0].lower()
    if first_word in COMMANDS:
        return [first_word] + words[1:]

    # A bare path: a file is checked, a folder is scanned
    if len(words) == 1:
        path = Path(words[0])
        if path.is_file():
            return ["check", words[0]]
        if path.is_dir():
            return ["scan", words[0]]
    return None


# Runs one TrueBit command through the same code as the normal command line
def run_command(command_words):
    from truebit.cli import app

    click_command = typer.main.get_command(app)
    try:
        click_command.main(args=command_words, prog_name="truebit", standalone_mode=False)
    except click.exceptions.ClickException as error:
        error.show()
    except (click.exceptions.Exit, click.exceptions.Abort, SystemExit):
        pass
    except KeyboardInterrupt:
        console.print(Text("  Stopped.", style=DIM))


# The main loop: prompt, run, repeat
def start_shell():
    while True:
        try:
            line = console.input(f"[bold {BLUE}]truebit[/] [{DIM}]›[/] ")
        except (KeyboardInterrupt, EOFError):
            console.print()
            break

        line = line.strip()
        if line == "":
            continue
        if line.lower() in EXIT_WORDS:
            break
        if line.lower() in ["help", "/help", "?"]:
            show_help()
            continue
        if line.lower() in ["clear", "cls"]:
            console.clear()
            continue

        command_words = to_command_words(split_command(line))
        if command_words is None:
            console.print(Text("  Unknown command. Type ", style=RED) + Text("help", style=BLUE)
                          + Text(" to see what TrueBit can do.", style=RED))
            continue

        console.print()
        run_command(command_words)
        console.print()

    console.print(Text("  Bye! 🎧", style=DIM))
