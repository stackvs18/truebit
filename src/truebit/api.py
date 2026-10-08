# The TrueBit web API, started with `truebit serve`.
#
#   GET  /           a small upload page
#   GET  /health     is the server running?
#   GET  /install.ps1  the short install link:  irm https://<this site>/install.ps1 | iex
#   POST /analyze    upload an audio file (max 50 MB), get the full report as JSON
#                    ?spectrogram=true also returns the spectrogram picture (base64 PNG)
#
# Each visitor (IP address) gets 5 analyses per day. After that: HTTP 429 with a
# Retry-After header saying how many seconds until midnight (India time).

import base64
import os
import shutil
import tempfile
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from truebit import __version__
from truebit.formats import AUDIO_EXTENSIONS
from truebit.probe import AudioError
from truebit.quota import DailyQuota
from truebit.report import analyze_file, save_spectrogram

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
CHUNK_BYTES = 1024 * 1024
INSTALL_SCRIPT_URL = "https://raw.githubusercontent.com/stackvs18/truebit/main/install.ps1"


# The visitor's IP address. Behind a host like Render, the real one is the first entry
# of the X-Forwarded-For header (the proxy's own address is the connection's address).
def visitor_ip(request):
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


# Saves the upload to a temporary file, stopping if it goes over the size limit
async def save_upload(upload, folder):
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Please upload an audio file (FLAC, WAV, MP3, M4A, OGG...).")

    file_path = Path(folder) / ("upload" + extension)
    total_bytes = 0
    with open(file_path, "wb") as output:
        while True:
            chunk = await upload.read(CHUNK_BYTES)
            if not chunk:
                break
            total_bytes = total_bytes + len(chunk)
            if total_bytes > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="File is larger than 50 MB.")
            output.write(chunk)
    return file_path


# Builds the FastAPI app. The quota database and limit can be changed (the tests use this).
def create_app(quota_database=None, daily_limit=5):
    if quota_database is None:
        quota_database = os.environ.get("TRUEBIT_QUOTA_DB", str(Path(tempfile.gettempdir()) / "truebit-quota.db"))
    quota = DailyQuota(quota_database, daily_limit)

    app = FastAPI(title="TrueBit", version=__version__,
                  description="Detect fake lossless and fake 320 kbps audio.")

    # The upload page
    @app.get("/", response_class=HTMLResponse)
    def home():
        return resources.files("truebit").joinpath("upload.html").read_text(encoding="utf-8")

    # Is the server running?
    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    # The short install link. It sends PowerShell on to the script on GitHub (irm follows
    # redirects), so there is only ever one copy of the installer.
    @app.get("/install.ps1")
    def install_script():
        return RedirectResponse(INSTALL_SCRIPT_URL)

    # Analyse one uploaded file
    @app.post("/analyze")
    async def analyze(request: Request, file: UploadFile, spectrogram: bool = False):
        ip_address = visitor_ip(request)

        # Step 1: check the daily limit
        allowed, remaining = quota.take_one(ip_address)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": f"Daily limit of {daily_limit} analyses reached. Try again tomorrow."},
                headers={"Retry-After": str(quota.seconds_until_reset())},
            )

        # Step 2: save the upload, analyse it, then delete it (nothing is kept)
        folder = tempfile.mkdtemp(prefix="truebit-")
        try:
            file_path = await save_upload(file, folder)
            report = analyze_file(file_path)
            if spectrogram:
                image_path = save_spectrogram(file_path)
                if image_path is not None:
                    report["spectrogram_png_base64"] = base64.b64encode(image_path.read_bytes()).decode()
        except HTTPException:
            quota.give_back(ip_address)
            raise
        except AudioError as error:
            quota.give_back(ip_address)
            raise HTTPException(status_code=422, detail=str(error))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        return JSONResponse(content=report, headers={"X-Quota-Remaining": str(remaining)})

    return app
