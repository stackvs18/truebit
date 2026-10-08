# TrueBit

**Catch fake lossless and fake 320 kbps audio, then repair and normalize what you keep. From your terminal.**

A file sold or shared as "FLAC" or "320 kbps" is often just a 128 kbps MP3 converted upwards. TrueBit finds the fingerprint every MP3/AAC encoder leaves, a sharp **frequency cliff**, and tells you what the file really is.

```powershell
irm https://raw.githubusercontent.com/stackvs18/truebit/main/install.ps1 | iex
truebit                                   # opens TrueBit: type commands or drag in a file
truebit check "song.flac"                 # real or fake?
truebit scan "D:\Music" --json report.json
truebit compare "a.flac" "b.mp3"          # which copy is genuinely better?
truebit repair "old_recording.wav"        # fix clipping, clicks and hiss
truebit normalize "song.flac"             # -14 LUFS, like Spotify
```

![truebit check](docs/check.png)

## Install

Paste one line into **PowerShell** (Windows 10/11):

```powershell
irm https://raw.githubusercontent.com/stackvs18/truebit/main/install.ps1 | iex
```

It installs FFmpeg (with winget) and [uv](https://docs.astral.sh/uv/) if you don't have them, then
TrueBit itself, and puts `truebit` on your PATH. Running it again updates TrueBit.
Remove it with `uv tool uninstall truebit`. Once the web app is live, its short link does the same:
`irm https://<your-site>/install.ps1 | iex`.

macOS / Linux: install FFmpeg and uv, then `uv tool install git+https://github.com/stackvs18/truebit`.

---

## How it works

1. **Read the file** with `ffprobe`: codec, container, bitrate, sample rate, bit depth.
2. **Decode** it with `ffmpeg` into raw samples (numpy).
3. **Spectrum:** Welch's method (FFT of many short overlapping pieces, averaged) gives the energy at every frequency.
4. **Find the cliff:** average level in 250 Hz bands from 14 kHz up. The cliff is the biggest drop between neighbouring bands, if it's at least 20 dB and everything above stays quiet.
5. **Verdict:** a lossless container with a cliff = **fake lossless**; an MP3 claiming far more bitrate than its cliff allows = **fake bitrate**.

| Cliff at | Likely source |
|---|---|
| below 17.25 kHz | ~128 kbps |
| 17.25 – 18.8 kHz | ~160–192 kbps |
| 18.8 – 19.8 kHz | ~256 kbps / V0 |
| 19.8 – 20.8 kHz | ~320 kbps |
| no cliff | consistent with real lossless |

These are estimates (encoders differ slightly), calibrated on files made with LAME through FFmpeg.

It also reports **loudness**: EBU R128 integrated loudness (LUFS), true peak, crest factor and clipped samples (measured on every channel). With `--save` it writes `song.truebit.json` and a spectrogram picture into `./truebit-reports/`, never next to your music, so your library is never changed.

**Try it on a fake you make yourself:**
```powershell
ffmpeg -i song.flac -b:a 128k small.mp3
ffmpeg -i small.mp3 fake.flac
truebit check fake.flac          # FAKE LOSSLESS: upscaled from ~128 kbps
```

---

## Commands

| Command | What it does |
|---|---|
| `truebit` | Opens TrueBit's interactive mode: a `truebit ›` prompt where you type commands or drag in a file/folder; `help`, `exit` |
| `truebit check FILE` | Full report: verdict, details, loudness, band chart |
| `truebit check FILE --save` | Also saves the JSON report and a spectrogram to `./truebit-reports/` |
| `truebit scan FOLDER` | Table of every audio file in a folder (and sub-folders) |
| `truebit scan FOLDER --json report.json` | Also saves all reports |
| `truebit compare A B` | Which of two copies of a song is genuinely better (by real cutoff, not the label) |
| `truebit repair FILE` | Rebuilds clipped peaks, removes clicks, reduces hiss; shows before/after numbers |
| `truebit repair FILE --strength strong --no-declick` | Choose how hard to denoise and which steps to run |
| `truebit normalize FILE` | Sets loudness to -14 LUFS (Spotify/YouTube); `--preset apple` (-16), `broadcast` (-23), or `--target -12` |
| `truebit serve` | Web API and upload page |

Supported: FLAC, WAV, MP3, M4A/AAC, OGG, Opus, ALAC, AIFF, WMA (anything FFmpeg reads).

---

## Interactive mode and the look

Type `truebit` and it opens like an app (the way `claude` opens Claude Code): a TRUEBIT logo,
then a `truebit ›` prompt that stays open until `exit`. Type any command, or just drag a file
(checked) or a folder (scanned) into the window and press Enter.

The look is TrueBit's own, in macOS blue: `◆` for each action, `╰─` for its result, and an
animated **equalizer** (`▂▅▇▃`) while it works, with a shimmering verb that changes every 2 seconds
and a live timer: `▅▇▃▂ Sniffing for brickwalls… (12s · 4.2 MB · ctrl+c to stop)`.

## Repair, normalize and compare

**`repair`** chains FFmpeg's restoration filters:
`adeclick` (fills in short spikes) → `adeclip` (rebuilds the tops of clipped waves) →
`afftdn` (turns down steady hiss; TrueBit measures the noise floor first and tells the filter
where the hiss sits) → `alimiter` (so repaired peaks don't clip again).
On a test file: **75,482 clipped samples → 0, background noise −35.3 → −49.7 dB** (strong).
It fixes damage. It cannot bring back frequencies an MP3 encoder deleted, and it says so.

**`normalize`** runs EBU R128 `loudnorm` in two passes: measure first, then one exact gain change
(`linear=true` keeps the dynamics). On a test file: −48.75 → −14.0 LUFS with true peak at −0.9 dBTP.

**`compare`** ranks by what's really in the files: genuine lossless first, then the higher real
cutoff, then fewer clipped samples. A "FLAC" at 1131 kbps loses to a real FLAC at 890 kbps.

Outputs are saved next to the input (`song.repaired.flac`, `song.normalized-14.flac`). Lossy inputs
are saved as FLAC, so the fix adds no further loss.

## Web API

```powershell
truebit serve                      # http://127.0.0.1:8000  (upload page)  ·  /docs for the API
```

| Endpoint | What it does |
|---|---|
| `GET /` | Drag-and-drop upload page |
| `POST /analyze` | Upload a file (max 50 MB), get the full JSON report; `?spectrogram=true` adds the picture as base64 |
| `GET /health` | Status |
| `GET /install.ps1` | Short install link: redirects to `install.ps1` on GitHub, so `irm https://<your-site>/install.ps1 \| iex` works |

- **5 analyses per IP per day**, resetting at midnight India time (SQLite table `usage(ip, day, count)`). Over the limit: `429` with `Retry-After` (seconds until midnight). Remaining uses are in the `X-Quota-Remaining` header.
- Behind a proxy (Render), the real IP is the first entry of `X-Forwarded-For`.
- Uploads are written to a temp folder, analysed and deleted immediately. A broken or non-audio file doesn't use up a turn.
- **Docker:** `docker build -t truebit . && docker run -p 8000:8000 truebit` (the image includes FFmpeg).
- **Deploy on Render (free):** New → **Blueprint** → this repo. [`render.yaml`](render.yaml) builds the
  Dockerfile in Singapore and checks `/health`. The free plan sleeps after 15 idle minutes (the first
  visit then takes about a minute), and the daily-limit counts reset when it restarts.

## Project structure

```
src/truebit/
  probe.py      ffprobe file details + ffmpeg decoding
  spectrum.py   Welch spectrum, band levels, find_cutoff()
  verdict.py    cutoff -> likely source -> verdict
  loudness.py   EBU R128 (ffmpeg ebur128), peak, RMS, crest factor, clipping
  report.py     runs everything, saves JSON and spectrogram
  cli.py        every command (Typer)
  shell.py      interactive mode: the truebit › prompt, pasted paths
  ui.py         the look: macOS blue, equalizer spinner, logo
  api.py        FastAPI: upload page, /analyze, /health
  quota.py      5 analyses per IP per day (SQLite)
  repair.py     declick, declip, denoise, limiter
  normalize.py  two-pass EBU R128 loudness normalization
  compare.py    which copy is genuinely better
  output.py     shared: output file names, running FFmpeg filters
tests/          real test audio made with FFmpeg: verdicts, tools, API, quota, interactive mode (30 tests)
Dockerfile      Python + FFmpeg image for hosting the API
render.yaml     one-click Render deploy of that image
install.ps1     one-line Windows installer (FFmpeg + uv + TrueBit); re-run to update
```

## Develop

```powershell
git clone https://github.com/stackvs18/truebit
cd truebit
uv sync
uv run truebit check some_song.flac
uv run pytest

# Make `truebit` a real command (editable: code changes apply instantly)
uv tool install --editable .
```

## Tested on a real library

On 36 real songs (MP3 and AAC): **scan took 30 s and found 11 fakes**, for example a "320 kbps" MP3
with a 16.0 kHz cliff (really ~128 kbps). **Repair** took a heavily clipped track from
**1,626,790 clipped samples to 0** (true peak +4.8 → +1.8 dBTP); **normalize** took a +0.78 LUFS
master to exactly **−14 LUFS**.

Two bugs were found this way and fixed, each with a regression test:
1. Clipping was measured on a mono mix made by FFmpeg, which *adds* the channels, so a clean file
   peaking at 0.95 looked like it peaked at 1.29. Now peaks and clipping are measured on every
   channel, and mono is made by averaging.
2. FFmpeg's `loudnorm` rejects a measured loudness above 0 LUFS; very loud masters measure +0.78.
   The measurements are now kept inside the filter's allowed ranges.

## Next steps

- A machine-learning classifier: encode real lossless clips at 128/192/256/320 kbps (free labels), train on band energies, and report a confidence next to the rule-based verdict.
