#!/usr/bin/env python3
"""Upload this project folder to Nextcloud via WebDAV.

Usage:
    pip install requests
    export NEXTCLOUD_URL=https://your.nextcloud.example
    export NEXTCLOUD_USER=your_username
    export NEXTCLOUD_APP_PASSWORD=app_password   # Settings -> Security -> App passwords
    python upload_to_nextcloud.py --dest "Projects/Python/EpubToAnki"

If the env vars are not set, the script prompts for them (password hidden).
Files are uploaded preserving the folder structure; __pycache__/.git are skipped.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def ensure_folder(session: requests.Session, base: str, folder: str) -> None:
    parts = [p for p in folder.strip("/").split("/") if p]
    path = ""
    for part in parts:
        path += "/" + part
        resp = session.request("MKCOL", base + path)
        if resp.status_code not in (201, 405):  # 405 = already exists
            raise RuntimeError(f"MKCOL {path} -> {resp.status_code}: {resp.text[:200]}")


def upload_file(session: requests.Session, base: str, local: Path, remote: str) -> None:
    resp = session.put(base + remote, data=local.read_bytes())
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"PUT {remote} -> {resp.status_code}: {resp.text[:200]}")
    print(f"  uploaded {remote} ({local.stat().st_size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("NEXTCLOUD_URL", ""))
    parser.add_argument("--user", default=os.environ.get("NEXTCLOUD_USER", ""))
    parser.add_argument("--password", default=os.environ.get("NEXTCLOUD_APP_PASSWORD", ""))
    parser.add_argument("--dest", default="Projects/Python/EpubToAnki")
    parser.add_argument("--source", default=str(Path(__file__).parent))
    args = parser.parse_args()

    url = args.url or input("Nextcloud URL (e.g. https://cloud.example.com): ").strip().rstrip("/")
    user = args.user or input("Nextcloud username: ").strip()
    password = args.password or getpass.getpass("Nextcloud app password: ")
    if not url or not user or not password:
        print("URL, user and password are required.", file=sys.stderr)
        return 2

    base = f"{url}/remote.php/dav/files/{user}"
    dest = args.dest.strip("/")
    src = Path(args.source).resolve()

    session = requests.Session()
    session.auth = HTTPBasicAuth(user, password)
    session.headers["OCS-APIRequest"] = "true"

    print(f"Creating folders under /{dest} ...")
    ensure_folder(session, base, dest)

    files = [
        p for p in sorted(src.rglob("*"))
        if p.is_file()
        and not any(part in SKIP_DIRS for part in p.relative_to(src).parts)
        and p.suffix not in SKIP_SUFFIXES
        and p.name != Path(__file__).name
    ]
    print(f"Uploading {len(files)} files from {src} ...")
    for local in files:
        remote = f"/{dest}/" + local.relative_to(src).as_posix()
        upload_file(session, base, local, remote)

    print(f"Done. Files are in Nextcloud under /{dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
