from dataclasses import dataclass
import json
import re
import sqlite3
import unicodedata

import numpy as np

from .store import connect, current_snapshot, embedding_identity

ALIASES = {
    "音が出ない": "no sound monitoring routing", "ルーティング": "routing",
    "入出力": "routing input output", "録音": "recording", "遅延": "latency",
    "ギター": "guitar", "ベース": "bass", "入力": "input", "出力": "output",
    "モニター": "monitoring", "オペレーター": "Operator", "サンプラー": "Sampler",
    "シンプラー": "Simpler", "ウェーブテーブル": "Wavetable", "エコー": "Echo",
    "ドライ": "Dry", "ウェット": "Wet", "エフェクト": "effect",
    "外部": "external", "接続": "connection", "チャンネル": "channel",
    "違い": "difference", "ワープ": "warp", "オートメーション": "automation",
    "サイドチェイン": "sidechain", "音量": "volume", "同期": "sync",
}


def sampling_overview(query):
    """An underspecified sampling question needs an explicit, limited starting scope."""
    return bool(re.fullmatch(r"[\s？?。]*(?:サンプリング)(?:の|について|方法|やり方|使い方|を|教えて|おしえて|ください|下さい|したい|するには|[\s？?。])*", query))


def introductory(query, devices):
    rest = query.casefold()
    for device in sorted(devices, key=len, reverse=True):
        rest = rest.replace(device.casefold(), "")
    rest = re.sub(r"使い方|基本操作|基本|入門|概要|方法|について|おしえて|教えて|ください|下さい|how to use|getting started|overview|please|の|を|は|とは|ですか", "", rest)
    return bool(devices) and not re.sub(r"[\s？?。!！]", "", rest)


def version_tuple(value):
    if not re.fullmatch(r"\d+(\.\d+){0,2}", str(value)):
        raise ValueError("Liveバージョンは12.3.5のような数字で指定してください。")
    return tuple(int(x) for x in str(value).split(".")) + (0,) * (3 - len(str(value).split(".")))


def applicable(meta, version, edition):
    current = version_tuple(version)
    major = meta.get("live_major")
    if major is not None and int(major) != current[0]:
        return False
    if meta.get("live_min") and current < version_tuple(meta["live_min"]):
        return False
    if meta.get("live_max") and current > version_tuple(meta["live_max"]):
        return False
    if meta.get("editions") and edition not in meta["editions"]:
        return False
    return True


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    similarity: float | None = None
    rank_score: float = 0.0


class Retriever:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot or current_snapshot()
        self.manifest = json.loads((self.snapshot / "manifest.json").read_text())

    def search(self, query, version="12.3.5", edition="Suite", runtime=None, top_k=5):
        if not query.strip() or len(query) > 2000:
            raise ValueError("質問は1～2,000文字で入力してください。")
        query = unicodedata.normalize("NFKC", query)
        if sampling_overview(query):
            query = "Simplerの使い方"
        expanded = query + " " + " ".join(v for k, v in ALIASES.items() if k in query)
        db = connect(self.snapshot / "knowledge.sqlite")
        try:
            rows = db.execute("SELECT * FROM chunks").fetchall()
            devices = set()
            for row in rows:
                meta = json.loads(row["metadata"])
                if any(name in meta.get("document_id", "") for name in ("live-instrument-reference", "live-audio-effect-reference", "live-midi-effect-reference")):
                    headings = meta.get("heading_path", [])
                    if len(headings) > 1:
                        devices.add(re.sub(r"^[\d.]+\s*", "", headings[1]))
            named = [d for d in devices if len(d) > 2 and re.search(r"(?<![A-Za-z0-9])" + re.escape(d) + r"(?![A-Za-z0-9])", expanded, re.I)]
            overview = introductory(query, named)
            candidates = {}
            vectors, ids = [], []
            for row in rows:
                meta = json.loads(row["metadata"])
                if applicable(meta, version, edition):
                    heading_names = {re.sub(r"^[\d.]+\s*", "", h).casefold() for h in meta.get("heading_path", [])}
                    if named and not any(d.casefold() in heading_names for d in named):
                        continue
                    candidates[row["id"]] = Hit(row["id"], row["text"], meta)
                    if row["vector"]:
                        vectors.append(np.frombuffer(row["vector"], dtype="<f4"))
                        ids.append(row["id"])
            rankings = []
            if runtime and vectors:
                if self.manifest["embedding"] != embedding_identity():
                    raise ValueError("Embeddingモデルが索引と一致しません。索引を再作成してください。")
                q = runtime.embed(query, query=True)
                scores = np.stack(vectors) @ q
                for i, cid in enumerate(ids):
                    candidates[cid].similarity = float(scores[i])
                rankings.append([ids[i] for i in np.argsort(-scores)[:20]])
            terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]*|[\u3040-\u30ff\u3400-\u9fff]{3,}", expanded)
            terms = list(dict.fromkeys(terms))[:25]
            for table in ("words", "grams"):
                selected = [t for t in terms if table == "words" or len(t) >= 3]
                if not selected:
                    continue
                expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in selected)
                found = db.execute(f"SELECT id FROM {table} WHERE {table} MATCH ? ORDER BY bm25({table},0,4,1)", (expression,))
                rankings.append([r[0] for r in found if r[0] in candidates][:20])
            for ranking in rankings:
                for rank, cid in enumerate(ranking, 1):
                    candidates[cid].rank_score += 1 / (60 + rank)
            # Explicit UI labels such as Track / Sync / Remote are stronger than a generic MIDI heading.
            english = set(t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", expanded))
            for hit in candidates.values():
                leaf = re.sub(r"^[\d.]+\s*", "", (hit.metadata.get("heading_path") or [""])[-1]).lower()
                if leaf in english and leaf not in ("midi", "audio", "live") and not named:
                    hit.rank_score += 0.05
                if overview:
                    headings = hit.metadata.get("heading_path", [])
                    if len(headings) == 2:
                        hit.rank_score += 0.07
                        if re.search(r"drag(?:ged|ging)?|load(?:ed|ing)?", hit.text, re.I):
                            hit.rank_score += 0.04
                    if re.search(r"playback modes|getting started|loading samples", leaf):
                        hit.rank_score += 0.05
                        if re.search(r"(?:^|\n)1\. ", hit.text):
                            hit.rank_score += 0.04
            hits = sorted((h for h in candidates.values() if h.rank_score), key=lambda h: h.rank_score, reverse=True)
            if overview:
                # Introductory steps can span adjacent chunks under the same heading.
                return hits[:top_k]
            # Diversify sections, then fill remaining slots. HTML/PDF copies share canonical_id.
            selected, deferred, seen = [], [], set()
            for hit in hits:
                key = (hit.metadata.get("canonical_id", hit.metadata["document_id"]), tuple(hit.metadata["heading_path"]))
                if key in seen:
                    deferred.append(hit)
                else:
                    seen.add(key)
                    selected.append(hit)
                if len(selected) >= top_k:
                    break
            return (selected + deferred)[:top_k]
        finally:
            db.close()
