"""Recreate .venv entirely from local wheels; run with python3.12 from the project root."""
import json
from pathlib import Path
import subprocess
import sys
import venv
from .settings import ROOT, sha256


def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("保存済みwheelはPython 3.12用です。python3.12を使用してください。")
    checksums = json.loads((ROOT / "offline_bundle/checksums.json").read_text())
    for name, expected in checksums.items():
        path = ROOT / "offline_bundle/wheels" / name
        if not path.exists() or sha256(path) != expected:
            raise SystemExit("wheelが不足・破損しています: " + name)
    target = ROOT / ".venv"
    venv.EnvBuilder(with_pip=True).create(target)
    subprocess.run([str(target / "bin/python"), "-m", "pip", "install", "--no-index", "--disable-pip-version-check",
                    "--find-links", str(ROOT / "offline_bundle/wheels"), "-r", str(ROOT / "requirements.lock")], check=True)


if __name__ == "__main__":
    main()
