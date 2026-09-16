import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid

import numpy as np

from .ingestion import discover, parse
from .settings import ROOT, data_root, settings, sha256, write_json


def embedding_identity():
    manifest = ROOT / "models/manifest.json"
    if not manifest.exists():
        return "unavailable"
    entry = json.loads(manifest.read_text())["embedding"]
    return entry["sha256"] + ":last:l2:1024:instruction-v1"


def connect(path):
    db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def current_snapshot(root=None):
    root = Path(root or data_root())
    pointer = root / "current.json"
    if not pointer.exists():
        raise FileNotFoundError("知識ベースがありません。先に資料を取り込んでください。")
    sid = json.loads(pointer.read_text())["snapshot"]
    if not sid or Path(sid).name != sid:
        raise ValueError("不正なsnapshot ID")
    target = root / "snapshots" / sid
    if not (target / "knowledge.sqlite").is_file():
        raise FileNotFoundError("知識ベースのファイルがありません。旧snapshotへ復旧してください。")
    return target


def build_snapshot(runtime=None, knowledge=None, root=None, progress=None):
    root = Path(root or data_root())
    knowledge = Path(knowledge or ROOT / "knowledge")
    root.mkdir(parents=True, exist_ok=True)
    import fcntl
    lock = (root / "build.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("取り込み処理が既に実行中です。")
    sid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    target = root / "snapshots" / sid
    target.mkdir(parents=True)
    cfg = settings()["retrieval"]
    report = {"snapshot": sid, "created_at": datetime.now(timezone.utc).isoformat(),
              "embedding": embedding_identity() if runtime else None,
              "documents": [], "errors": [], "chunks": 0, "reused_vectors": 0}
    cache = {}
    try:
        old = current_snapshot(root)
        old_manifest = json.loads((old / "manifest.json").read_text())
        if runtime and old_manifest.get("embedding") == report["embedding"]:
            with contextlib.closing(connect(old / "knowledge.sqlite")) as db:
                cache = {r[0]: r[1] for r in db.execute("SELECT content_key, vector FROM chunks WHERE vector IS NOT NULL")}
    except FileNotFoundError:
        pass
    db = sqlite3.connect(target / "knowledge.sqlite")
    try:
        db.executescript("""
            CREATE TABLE chunks (id TEXT PRIMARY KEY, text TEXT, metadata TEXT, vector BLOB, content_key TEXT);
            CREATE VIRTUAL TABLE words USING fts5(id UNINDEXED, heading, text, tokenize='unicode61');
            CREATE VIRTUAL TABLE grams USING fts5(id UNINDEXED, heading, text, tokenize='trigram');
        """)
        documents = list(discover(knowledge))
        if not documents:
            raise ValueError("取り込み対象がありません。資料と.meta.jsonを配置してください。")
        for index, (path, meta) in enumerate(documents):
            if progress:
                progress(index, len(documents), path.name)
            try:
                chunks = parse(path, meta, cfg["chunk_chars"], cfg["overlap_chars"])
            except (ValueError, OSError) as exc:
                report["errors"].append({"file": str(path), "error": str(exc)})
                continue
            original = target / "originals" / (sha256(path) + path.suffix.lower())
            original.parent.mkdir(exist_ok=True)
            if not original.exists():
                shutil.copy2(path, original)
            for chunk in chunks:
                chunk.metadata["snapshot_source"] = str(original.relative_to(target))
                heading = " > ".join(chunk.metadata["heading_path"])
                embed_text = heading + "\n" + chunk.text
                key = hashlib.sha256(embed_text.encode()).hexdigest()
                vector = cache.get(key) if runtime else None
                if vector is not None:
                    report["reused_vectors"] += 1
                elif runtime:
                    vector = runtime.embed(embed_text).astype("<f4").tobytes()
                db.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)", (chunk.id, chunk.text, json.dumps(chunk.metadata, ensure_ascii=False), vector, key))
                db.execute("INSERT INTO words VALUES (?, ?, ?)", (chunk.id, heading, chunk.text))
                db.execute("INSERT INTO grams VALUES (?, ?, ?)", (chunk.id, heading, chunk.text))
            report["documents"].append({"title": meta.get("title", path.name), "file": str(path), "chunks": len(chunks), "sha256": sha256(path)})
            report["chunks"] += len(chunks)
        if not report["chunks"]:
            raise ValueError("使用できる資料がありません。")
        if report["errors"]:
            write_json(target / "manifest.json", report)
            raise ValueError("抽出エラーがあるため新しい索引を有効化しません。" + str(report["errors"][:3]))
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite整合性検査に失敗しました。")
        report["database_sha256"] = sha256(target / "knowledge.sqlite")
        write_json(target / "manifest.json", report)
        write_json(root / "current.json", {"snapshot": sid})
        return report
    finally:
        db.close()
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def activate(sid, root=None):
    root = Path(root or data_root())
    if Path(sid).name != sid or sid in ("", ".", ".."):
        raise ValueError("不正なsnapshot ID")
    target = root / "snapshots" / sid
    manifest = json.loads((target / "manifest.json").read_text())
    if manifest.get("errors") or sha256(target / "knowledge.sqlite") != manifest["database_sha256"]:
        raise ValueError("整合性検査に失敗したsnapshotは使用できません。")
    write_json(root / "current.json", {"snapshot": sid})
