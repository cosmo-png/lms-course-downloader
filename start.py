#!/usr/bin/env python3
"""One-command launcher: python start.py   (works on Windows, Linux, macOS, any shell)
Creates a private virtual environment on first run, installs requirements, then runs the tool."""
import hashlib
import subprocess
import sys
import venv
from pathlib import Path

here = Path(__file__).resolve().parent
vdir = here / ".venv"
py = vdir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
req = here / "requirements.txt"
marker = vdir / ".req_hash"
want = hashlib.sha256(req.read_bytes()).hexdigest()

if not py.exists() or not marker.exists() or marker.read_text() != want:
    print("Setting up (first run only, takes a minute)...")
    if not py.exists():
        venv.create(vdir, with_pip=True)
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "-r", str(req)])
    marker.write_text(want)

raise SystemExit(subprocess.call([str(py), str(here / "lms_dl.py"), *sys.argv[1:]]))
