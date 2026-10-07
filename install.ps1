# TrueBit installer for Windows.
#
#   irm https://raw.githubusercontent.com/stackvs18/truebit/main/install.ps1 | iex
#
# It installs FFmpeg (if missing) and uv (a Python tool manager), then TrueBit itself.
# Always read a script before piping it into iex. This one only installs those three things.

$ErrorActionPreference = "Stop"
Write-Host ""
Write-Host "  T R U E B I T" -ForegroundColor Cyan
Write-Host "  catch fake lossless and fake 320 kbps audio" -ForegroundColor DarkCyan
Write-Host ""

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "[1/3] Installing FFmpeg..." -ForegroundColor Yellow
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "[1/3] FFmpeg is already installed" -ForegroundColor Green
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[2/3] Installing uv..." -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
} else {
    Write-Host "[2/3] uv is already installed" -ForegroundColor Green
}

Write-Host "[3/3] Installing TrueBit..." -ForegroundColor Yellow
uv tool install --force git+https://github.com/stackvs18/truebit
uv tool update-shell | Out-Null

Write-Host ""
Write-Host "Done! Open a NEW terminal and try:" -ForegroundColor Green
Write-Host '    truebit check "song.flac"'
Write-Host '    truebit scan "D:\Music" --json report.json'
Write-Host ""
