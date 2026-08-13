#!/usr/bin/env python3
"""Download and verify the IUCr QARR CPI archive despite its browser challenge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path


ARCHIVE_URL = "https://www.iucr.org/__data/iucr/powder/QARR/cpi.zip"
ARCHIVE_SHA256 = "5205385b58af5b81685cf1466d5d054ae42c056252c50f97eaed8737337b4197"
REQUIRED_STEMS = (
    "cpd-1a", "cpd-1b", "cpd-1c", "cpd-1d", "cpd-1e", "cpd-1f", "cpd-1g", "cpd-1h",
    "cpd-2", "cpd-3", "cpd-4", "bauxite", "granodio", "pharm1gr", "pharm2gr",
    "corundum", "fluorite", "zincite", "brucite", "magnetit",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_archive(path: Path) -> bool:
    return path.is_file() and _sha256(path) == ARCHIVE_SHA256 and zipfile.is_zipfile(path)


def _direct_download(target: Path) -> bool:
    request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as stream:
            shutil.copyfileobj(response, stream)
    except Exception:
        target.unlink(missing_ok=True)
        return False
    return _valid_archive(target)


def _start_xvfb() -> tuple[subprocess.Popen[bytes] | None, str | None]:
    if os.environ.get("DISPLAY"):
        return None, None
    executable = shutil.which("Xvfb")
    if executable is None:
        raise RuntimeError("Xvfb is required for the browser fallback; install package xvfb")
    for number in range(90, 111):
        if Path(f"/tmp/.X11-unix/X{number}").exists():
            continue
        process = subprocess.Popen(
            [executable, f":{number}", "-screen", "0", "1365x900x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        if process.poll() is None:
            display = f":{number}"
            os.environ["DISPLAY"] = display
            return process, display
    raise RuntimeError("could not start an Xvfb display")


def _browser_download(target: Path) -> None:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for the IUCr browser fallback; run "
            "'.venv/bin/pip install playwright && .venv/bin/playwright install chromium'"
        ) from exc

    xvfb, display = _start_xvfb()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False, args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                accept_downloads=True,
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
                ),
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()
            with page.expect_download(timeout=180_000) as pending:
                try:
                    page.goto(ARCHIVE_URL, wait_until="commit", timeout=180_000)
                except Error as exc:
                    if "Download is starting" not in str(exc):
                        raise
            download = pending.value
            download.save_as(target)
            browser.close()
    finally:
        if xvfb is not None:
            xvfb.terminate()
            xvfb.wait(timeout=10)
        if display is not None:
            os.environ.pop("DISPLAY", None)
    if not _valid_archive(target):
        target.unlink(missing_ok=True)
        raise RuntimeError("downloaded IUCr archive failed the pinned SHA-256 check")


def extract_required(archive: Path, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=True)
    checksums: dict[str, str] = {}
    with zipfile.ZipFile(archive) as bundle:
        members = {Path(name).name.lower(): name for name in bundle.namelist()}
        for stem in REQUIRED_STEMS:
            filename = f"{stem}.cpi"
            member = members.get(filename)
            if member is None:
                raise RuntimeError(f"IUCr archive lacks required member: {filename}")
            target = destination / filename
            target.write_bytes(bundle.read(member))
            checksums[filename] = _sha256(target)
    return checksums


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, default=Path("benchmarks/data/iucr_qarr/cpi.zip")
    )
    parser.add_argument(
        "--destination", type=Path,
        default=Path("benchmarks/autoxrd_bench_100/data/iucr"),
    )
    args = parser.parse_args()
    args.archive.parent.mkdir(parents=True, exist_ok=True)

    method = "cached"
    if not _valid_archive(args.archive):
        temporary = Path(tempfile.mkstemp(prefix="iucr-qarr-", suffix=".zip")[1])
        try:
            if _direct_download(temporary):
                method = "direct"
            else:
                method = "playwright"
                _browser_download(temporary)
            shutil.copyfile(temporary, args.archive)
        finally:
            temporary.unlink(missing_ok=True)
    checksums = extract_required(args.archive, args.destination)
    print(json.dumps({
        "archive": str(args.archive),
        "archive_sha256": _sha256(args.archive),
        "download_method": method,
        "destination": str(args.destination),
        "ready": len(checksums),
        "files": checksums,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
