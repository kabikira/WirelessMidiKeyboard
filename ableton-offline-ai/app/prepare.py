"""Explicit online model/runtime acquisition, pinned by SHA-256. Not an app startup path."""
import json
from pathlib import Path
import tarfile
import urllib.request
from .settings import ROOT, sha256


def download(url, target, expected):
    if target.exists() and sha256(target) == expected:
        print("検証済み:", target.name, flush=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as out:
        while block := response.read(1024 * 1024):
            out.write(block)
    if sha256(part) != expected:
        raise ValueError(f"ハッシュ不一致。既存ファイルを維持します: {target}")
    part.replace(target)


def main():
    manifest = json.loads((ROOT / "models/manifest.json").read_text())
    for kind in ("generation", "embedding"):
        m = manifest[kind]
        target = ROOT / m["file"]
        url = f"https://huggingface.co/{m['repo']}/resolve/{m['revision']}/{target.name}"
        download(url, target, m["sha256"])
    release = manifest["runtime"]["release"]
    archive = ROOT / "offline_bundle" / f"llama-{release}-macos-arm64.tar.gz"
    download(f"https://github.com/ggml-org/llama.cpp/releases/download/{release}/llama-{release}-bin-macos-arm64.tar.gz", archive, manifest["runtime"]["archive_sha256"])
    runtime = ROOT / "runtime/llama.cpp"
    runtime.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(runtime, filter="data")
    print("モデルと実行環境を準備しました。", flush=True)


if __name__ == "__main__":
    main()
