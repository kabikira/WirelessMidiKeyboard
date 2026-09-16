import atexit
import json
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from .settings import ROOT, settings, sha256


class Runtime:
    """Owns its children only; never downloads or adopts an unknown server."""
    def __init__(self):
        self.cfg = settings()["runtime"]
        self.processes = {}
        self.logfiles = {}
        self.last_used = time.monotonic()
        self.lock = threading.RLock()
        self.busy = 0
        self.closed = False
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.key = secrets.token_hex(24)
        self.verified = set()
        threading.Thread(target=self._idle_loop, daemon=True).start()
        atexit.register(self.close)

    def binary(self):
        candidates = list((ROOT / "runtime/llama.cpp").rglob("llama-server"))
        if not candidates:
            raise FileNotFoundError("llama.cppがありません。オンライン準備を実行してください。")
        return sorted(candidates, key=lambda p: len(p.parts))[0]

    def _request(self, kind, endpoint, body=None, timeout=180):
        port = self.cfg[f"{kind}_port"]
        url = f"http://127.0.0.1:{port}/{endpoint}"
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        with self.http.open(request, timeout=timeout) as response:
            return json.load(response)

    def start(self, kind):
        with self.lock:
            if kind in self.processes and self.processes[kind].poll() is None:
                return
            self.stop(kind)
            model = ROOT / self.cfg[f"{kind}_model"]
            if not model.is_file():
                raise FileNotFoundError(f"モデルがありません（自動取得しません）: {model.name}")
            with model.open("rb") as f:
                if f.read(4) != b"GGUF":
                    raise ValueError("モデルファイルが壊れています。")
            fingerprint = (kind, model.stat().st_size, model.stat().st_mtime_ns)
            if fingerprint not in self.verified:
                manifest = json.loads((ROOT / "models/manifest.json").read_text())
                if sha256(model) != manifest[kind]["sha256"]:
                    raise ValueError("モデルのハッシュが一致しません。検証済みファイルを復元してください。")
                self.verified.add(fingerprint)
            binary = self.binary()
            with socket.socket() as probe:
                # An exited server may leave TIME_WAIT sockets; do not mistake them for a listener.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(("127.0.0.1", self.cfg[f"{kind}_port"]))
                except OSError as exc:
                    raise RuntimeError("ローカルポートを確保できません。別のAIアプリ起動を終了してください。") from exc
            args = [str(binary), "-m", str(model), "--offline", "--host", "127.0.0.1",
                    "--port", str(self.cfg[f"{kind}_port"]), "-t", str(self.cfg["threads"]),
                    "-np", "1", "--no-webui", "--api-key", self.key]
            if kind == "generation":
                args += ["-c", str(self.cfg["context"]), "-ngl", "99", "-b", "256", "-ub", "128",
                         "--reasoning-budget", "0"]
            else:
                args += ["--embedding", "--pooling", "last", "-c", "2048", "-b", "2048",
                         "-ub", "2048", "-ngl", "99"]
            (ROOT / "logs").mkdir(exist_ok=True)
            log = (ROOT / f"logs/{kind}.log").open("ab")
            self.logfiles[kind] = log
            process = subprocess.Popen(args, stdout=log, stderr=log, cwd=ROOT)
            self.processes[kind] = process
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"{kind}の起動に失敗しました。logs/{kind}.logを確認してください。")
                try:
                    if self._request(kind, "health", timeout=2).get("status") == "ok":
                        self.last_used = time.monotonic()
                        return
                except (OSError, ValueError):
                    pass
                time.sleep(0.25)
            self.stop(kind)
            raise TimeoutError(f"{kind}の起動がタイムアウトしました。")

    def call(self, kind, endpoint, body):
        with self.lock:
            self.busy += 1
            try:
                self.start(kind)
                return self._request(kind, endpoint, body)
            finally:
                self.last_used = time.monotonic()
                self.busy -= 1

    def tokenize(self, kind, text):
        return self.call(kind, "tokenize", {"content": text, "add_special": True})["tokens"]

    def embed(self, text, query=False):
        import numpy as np
        if query:
            text = "Instruct: Given a question about Ableton Live, retrieve passages that answer the question.\nQuery: " + text
        if len(self.tokenize("embedding", text)) > 2000:
            raise ValueError("Embedding入力が長すぎます。資料を細かく分割してください。")
        result = self.call("embedding", "v1/embeddings", {"input": text})
        vector = np.asarray(result["data"][0]["embedding"], dtype=np.float32)
        norm = np.linalg.norm(vector)
        if vector.size != 1024 or not np.isfinite(vector).all() or norm == 0:
            raise ValueError("不正なEmbeddingです。索引は更新されません。")
        return vector / norm

    def generate(self, messages, schema):
        return self.call("generation", "v1/chat/completions", {
            "messages": messages, "temperature": 0.2,
            "max_tokens": self.cfg["max_output_tokens"],
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
        })

    def stop(self, kind="generation"):
        with self.lock:
            process = self.processes.pop(kind, None)
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log = self.logfiles.pop(kind, None)
            if log:
                log.close()

    def close(self):
        self.closed = True
        for kind in ("generation", "embedding"):
            self.stop(kind)

    def _idle_loop(self):
        while not self.closed:
            time.sleep(10)
            if not self.busy and time.monotonic() - self.last_used > self.cfg["idle_seconds"]:
                self.stop("generation")

    def status(self):
        return {k: p.pid for k, p in self.processes.items() if p.poll() is None}
