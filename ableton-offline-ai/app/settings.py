from pathlib import Path
import hashlib
import json
import os
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def settings():
    with (ROOT / "config/app.toml").open("rb") as f:
        return tomllib.load(f)


def data_root():
    return Path(os.environ.get("ABLETON_AI_DATA", str(ROOT / "data"))).resolve()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
