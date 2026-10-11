# Tests for the web API: analysis, the daily limit, the size limit and bad files.

import subprocess

import pytest
from fastapi.testclient import TestClient

from truebit.api import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(quota_database=str(tmp_path / "quota.db"), daily_limit=2)
    return TestClient(app)


@pytest.fixture(scope="module")
def fake_flac(tmp_path_factory):
    folder = tmp_path_factory.mktemp("api_audio")
    mp3_path = folder / "small.mp3"
    flac_path = folder / "fake.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:r=44100:a=0.3",
                    "-b:a", "128k", str(mp3_path)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3_path), str(flac_path)], check=True)
    return flac_path


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_upload_page(client):
    assert "really lossless" in client.get("/").text


def test_short_install_link_points_to_the_script_on_github(client):
    response = client.get("/install.ps1", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].endswith("/stackvs18/truebit/main/install.ps1")


def test_analyze_finds_the_fake(client, fake_flac):
    with open(fake_flac, "rb") as file:
        response = client.post("/analyze", files={"file": ("fake.flac", file, "audio/flac")})
    assert response.status_code == 200
    assert response.json()["verdict"] == "fake_lossless"
    assert response.json()["bitrate"]["real_kbps"] is not None  # a real cutoff was found
    assert response.json()["lossless"]["is_lossless"] is False
    assert response.headers["X-Quota-Remaining"] == "1"


def test_daily_limit_returns_429(client, fake_flac):
    for attempt in range(2):
        with open(fake_flac, "rb") as file:
            assert client.post("/analyze", files={"file": ("a.flac", file)}).status_code == 200
    with open(fake_flac, "rb") as file:
        response = client.post("/analyze", files={"file": ("a.flac", file)})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_each_ip_has_its_own_limit(client, fake_flac):
    for attempt in range(2):
        with open(fake_flac, "rb") as file:
            client.post("/analyze", files={"file": ("a.flac", file)}, headers={"X-Forwarded-For": "1.1.1.1"})
    with open(fake_flac, "rb") as file:
        response = client.post("/analyze", files={"file": ("a.flac", file)}, headers={"X-Forwarded-For": "2.2.2.2"})
    assert response.status_code == 200


def test_non_audio_is_rejected_and_not_counted(client):
    response = client.post("/analyze", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400
    assert client.post("/analyze", files={"file": ("notes.txt", b"hello")}).status_code == 400  # still not 429


def test_broken_audio_is_422(client):
    response = client.post("/analyze", files={"file": ("broken.flac", b"not really audio", "audio/flac")})
    assert response.status_code == 422
