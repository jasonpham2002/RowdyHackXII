"""Download the MediaPipe FaceLandmarker model used by the tracker.

Usage:
    python download_model.py
"""

from __future__ import annotations

import urllib.request

import config


def main() -> None:
    dest = config.MODEL_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"Model already present: {dest} ({dest.stat().st_size} bytes)")
        return
    print(f"Downloading {config.MODEL_URL}\n  -> {dest}")
    urllib.request.urlretrieve(config.MODEL_URL, dest)
    print(f"Done ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
