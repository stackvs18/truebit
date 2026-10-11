# TrueBit installer for Windows. Paste this into PowerShell:
#
#   irm https://raw.githubusercontent.com/stackvs18/truebit/main/install.ps1 | iex
#
# (once the website is live, this shorter one works too: irm https://<your-site>/install.ps1 | iex)
#
# What it does, step by step:
#   1. FFmpeg: installs it with winget if you don't have it (TrueBit uses it to read audio)
#   2. uv:     installs it if you don't have it (it downloads Python and keeps TrueBit in its own folder)
#   3. TrueBit: installs the newest version from GitHub and puts `truebit` on your PATH
#
# Running it again updates TrueBit. Remove TrueBit any time with:  uv tool uninstall truebit
# Always read a script before piping it into iex. This one only installs those three things.

# Everything is inside a function, so nothing leaks into your PowerShell session
function Install-TrueBit {
    $ErrorActionPreference = "Stop"

    # Where TrueBit comes from. Set $env:TRUEBIT_SOURCE to install a fork or a local folder.
    $source = "git+https://github.com/stackvs18/truebit"
    if ($env:TRUEBIT_SOURCE) {
        $source = $env:TRUEBIT_SOURCE
    }

    # TrueBit's colours (macOS blue, green, grey)
    $escape = [char]27
    $blue = "$escape[38;2;10;132;255m"
    $green = "$escape[38;2;48;209;88m"
    $red = "$escape[38;2;255;69;58m"
    $dim = "$escape[38;2;142;142;147m"
    $reset = "$escape[0m"

    # Prints one step the way TrueBit itself does:  ◆ FFmpeg  already installed
    function Write-Step($name, $detail) {
        Write-Host "${blue}◆${reset} $name  ${dim}$detail${reset}"
    }

    # Re-reads PATH from Windows, so a program installed a moment ago can be found
    function Update-PathFromWindows {
        $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path = "$machinePath;$userPath;$env:Path"
    }

    Write-Host ""
    Write-Host "  ${blue}▀█▀ █▀█ █ █ █▀▀ █▄▄ █ ▀█▀${reset}"
    Write-Host "  ${blue} █  █▀▄ █▄█ ██▄ █▄█ █  █ ${reset}"
    Write-Host "  ${dim}installer · is your FLAC really lossless?${reset}"
    Write-Host ""

    # Step 1: FFmpeg
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        Write-Step "FFmpeg" "already installed"
    } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Step "FFmpeg" "installing with winget (about a minute)..."
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
        Update-PathFromWindows
    } else {
        Write-Host "${red}FFmpeg is missing and winget isn't available.${reset}"
        Write-Host "Install FFmpeg from https://www.gyan.dev/ffmpeg/builds/ and run this again."
        return
    }

    # Step 2: uv
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Step "uv" "already installed"
    } else {
        Write-Step "uv" "installing (it manages Python for TrueBit)..."
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        Update-PathFromWindows
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    }

    # Step 3: TrueBit. --force replaces an older install, --upgrade fetches the newest version.
    Write-Step "TrueBit" "installing from $source..."
    uv tool install --force --upgrade $source
    if ($LASTEXITCODE -ne 0) {
        Write-Host "${red}Installing TrueBit failed (see the message above).${reset}"
        return
    }

    # Step 4: make sure the folder with truebit.exe is on PATH (only changes something once)
    $binFolder = (uv tool dir --bin)
    $pathFolders = $env:Path -split ";"
    if ($pathFolders -notcontains $binFolder) {
        uv tool update-shell | Out-Null
        $env:Path = "$binFolder;$env:Path"
    }

    # Step 5: check that it works
    Write-Host ""
    truebit version
    Write-Host ""
    Write-Host "${green}Done!${reset} Type ${blue}truebit${reset} to open it, or try:"
    Write-Host "    truebit check `"song.flac`""
    Write-Host "    truebit scan `"D:\Music`""
    Write-Host "${dim}If 'truebit' isn't found, open a new terminal window. Run this again any time to update.${reset}"
    Write-Host ""
}

Install-TrueBit
