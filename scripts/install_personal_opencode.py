"""Install the pinned official Windows CLI into this checkout's bin directory."""

import hashlib
import io
import zipfile
from pathlib import Path

import requests

VERSION = "v1.18.34"
ASSET = "opencode-windows-x64-baseline.zip"


def main():
    project = Path(__file__).resolve().parent.parent
    response = requests.get(f"https://api.github.com/repos/anomalyco/opencode/releases/tags/{VERSION}", timeout=30)
    response.raise_for_status()
    asset = next(item for item in response.json()["assets"] if item["name"] == ASSET)
    response = requests.get(asset["browser_download_url"], timeout=120)
    response.raise_for_status()
    digest = "sha256:" + hashlib.sha256(response.content).hexdigest()
    if asset.get("digest") and asset["digest"] != digest:
        raise RuntimeError("GitHub release asset checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        entry = next(name for name in archive.namelist() if Path(name).name == "opencode.exe")
        destination = project / "bin" / "opencode.exe"
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(archive.read(entry))
    print(f"Installed {VERSION}: {destination}\n{digest}")


if __name__ == "__main__":
    main()
