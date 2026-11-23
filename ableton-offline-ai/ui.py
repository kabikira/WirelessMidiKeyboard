from app.offline import enable
enable()

from dataclasses import asdict
import json
import re
from pathlib import Path
import threading
import uuid
from datetime import datetime, timezone

import streamlit as st

from app.answer import answer_question
from app.runtime import Runtime
from app.retrieval import Retriever, version_tuple
from app.settings import ROOT, data_root, settings, write_json
from app.store import build_snapshot, current_snapshot

st.set_page_config(page_title="Ableton Offline AI", page_icon="🎛", layout="wide")


@st.cache_resource
def resources():
    return Runtime(), threading.Lock()


runtime, work_lock = resources()
cfg = settings()
st.title("Ableton Offline AI")
st.caption("ローカル資料から調べる、Ableton Liveのためのアシスタント")

with st.sidebar:
    st.subheader("利用環境")
    version = st.text_input("Liveバージョン", cfg["profile"]["live_version"])
    edition = st.selectbox("Edition", ["Suite", "Standard", "Intro", "Lite"])
    search_only = st.toggle("検索のみ（生成モデルを使わない）", value=False)
    st.caption("通常の利用では外部接続しません。資料更新は別のコマンドから実行します。")
    if st.button("モデルを解放", width="stretch"):
        runtime.stop("generation")
        runtime.stop("embedding")
        st.success("モデルを停止しました。")
    save_history = st.toggle("回答履歴をこのMacに保存", value=True)
    st.caption("履歴は自動学習には使いません。内容を確認して、改善に反映したものだけ手動で記録します。")
    if not cfg["retrieval"]["calibrated"]:
        st.warning("試験運用：回答を控える閾値は未校正です。原文も確認してください。")

chat_tab, library_tab = st.tabs(["質問と根拠", "資料"])


def render_sources(hits, snapshot):
    for i, hit in enumerate(hits, 1):
        meta = hit["metadata"]
        heading = " > ".join(meta.get("heading_path", []))
        label = re.sub(r"([\\\[\]()!<>`*_])", r"\\\1", f"[{i}] {meta['title']} — {heading}")
        with st.expander(label):
            st.text(f"言語: {meta.get('language', '不明')} / 対象版: {meta.get('live_major', '不明')} / {meta.get('version_scope', 'unknown')}")
            if meta.get("pdf_page"):
                st.caption(f"PDF内 {meta['pdf_page']}ページ / ページ表記 {meta.get('page_label', '不明')}")
            st.text(hit["text"])
            st.caption(f"資料ID: {meta['document_id']} / 改訂: {meta['revision_id'][:12]}")
            if meta.get("url"):
                st.text("取得元: " + meta["url"])
            st.download_button("この根拠をテキスト保存", hit["text"], file_name=f"source-{hit['id']}.txt", key=f"download-{snapshot}-{hit['id']}-{i}")


with chat_tab:
    st.session_state.setdefault("chat_messages", [])
    if st.button("会話をクリア"):
        st.session_state["chat_messages"] = []
        st.session_state.pop("history_path", None)
        st.rerun()
    for turn_index, message in enumerate(st.session_state["chat_messages"]):
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.write(message["text"])
            else:
                result = message["result"]
                labels = {"supported": "根拠あり（自動検査）", "partial": "一部確認", "unknown": "確認できず", "search": "検索結果"}
                st.subheader(labels[result["status"]])
                for claim in result["claims"]:
                    st.text(f"{claim['text']} [{claim['source']}]")
                    st.caption("根拠原文")
                    st.text(claim["quote"])
                if result["reason"]:
                    st.text(result["reason"])
                history_path = message.get("history_path")
                if history_path and Path(history_path).is_file():
                    history_record = json.loads(Path(history_path).read_text(encoding="utf-8"))
                    status = history_record.get("improvement_status", "未確認")
                    st.caption(f"改善利用状況: {status}")
                    if status != "改善に反映済み" and st.button("この回答を改善に反映済みとして記録", key=f"mark-improvement-{turn_index}"):
                        history_record["improvement_status"] = "改善に反映済み"
                        history_record["improvement_used_at"] = datetime.now(timezone.utc).isoformat()
                        write_json(history_path, history_record)
                        st.success("改善への反映済みとして記録しました。")
                if result.get("seconds"):
                    st.caption(f"処理時間 {result['seconds']:.1f}秒 / snapshot {result['snapshot']}")
                render_sources(result["sources"], result["snapshot"])

    question = st.text_area("次の質問", placeholder="例：Simplerでサンプルを読み込むには？", max_chars=2000)
    if st.button("資料を調べる", type="primary", disabled=not question.strip()):
        if not work_lock.acquire(blocking=False):
            st.warning("別の処理が実行中です。終了後にお試しください。")
        else:
            try:
                version_tuple(version)
                with st.spinner("保存済み資料を検索しています…"):
                    retriever = Retriever()
                    conversation = [{"role": item["role"], "text": item["text"]}
                                    for item in st.session_state["chat_messages"][-6:]]
                    if search_only:
                        hits = retriever.search(question, version, edition)
                        result = {"status": "search", "reason": "全文検索の結果です。回答の根拠としての適合性は未判定です。",
                                  "claims": [], "sources": [asdict(h) for h in hits], "snapshot": retriever.snapshot.name}
                    else:
                        result = asdict(answer_question(question, retriever, runtime, version, edition, conversation))
                    history_path = None
                    if save_history:
                        history_path = data_root() / "history" / (uuid.uuid4().hex + ".json")
                        try:
                            turn_id = uuid.uuid4().hex
                            parent_turn_id = st.session_state["chat_messages"][-1].get("turn_id") if st.session_state["chat_messages"] else None
                            write_json(history_path, {"turn_id": turn_id, "parent_turn_id": parent_turn_id,
                                                      "question": question, "version": version, "result": result,
                                                      "improvement_status": "未確認", "improvement_used_at": None,
                                                      "improvement_note": ""})
                        except OSError as exc:
                            history_path = None
                            st.warning(f"回答は表示しますが、履歴を保存できませんでした: {exc}")
                    st.session_state["chat_messages"].append({"role": "user", "text": question})
                    assistant_text = "\n".join(c["text"] for c in result["claims"]) or result.get("reason", "")
                    st.session_state["chat_messages"].append({"role": "assistant", "text": assistant_text, "result": result,
                                                               "history_path": str(history_path) if history_path else None,
                                                               "turn_id": turn_id if save_history and history_path else None})
                    st.rerun()
            except Exception as exc:
                st.error(str(exc))
            finally:
                work_lock.release()
with library_tab:
    st.subheader("取り込み済み資料")
    try:
        snapshot = current_snapshot()
        manifest = json.loads((snapshot / "manifest.json").read_text())
        st.caption(f"{len(manifest['documents'])}資料 / {manifest['chunks']}チャンク / {snapshot.name}")
        st.dataframe(manifest["documents"], width="stretch")
    except FileNotFoundError:
        st.info("資料を配置して索引を作成してください。")
    st.subheader("ローカル資料を追加")
    uploaded = st.file_uploader("PDF / HTML / Markdown / Text", type=["pdf", "html", "htm", "md", "txt"], max_upload_size=40)
    title = st.text_input("資料名")
    kind = st.selectbox("資料の種類", ["personal_notes", "hardware"])
    major = st.selectbox("確認できている対象Live版", ["不明", "12", "11"])
    if st.button("資料を保存", disabled=uploaded is None or not title.strip()):
        name = uuid.uuid4().hex + Path(uploaded.name).suffix.lower()
        target = ROOT / "knowledge" / kind / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(uploaded.getvalue())
        write_json(target.with_name(target.name + ".meta.json"), {"document_id": uuid.uuid4().hex, "title": title,
                   "language": "unknown", "source_type": kind, "live_major": None if major == "不明" else int(major),
                   "version_scope": "unknown" if major == "不明" else "major_only", "verified": False})
        st.success("保存しました。下のボタンで検索索引を更新してください。")
    st.caption("索引の作成中はモデルを使用します。録音を停止してから実行してください。")
    if st.button("ローカル資料から索引を更新"):
        if not work_lock.acquire(blocking=False):
            st.warning("別の処理が実行中です。")
        else:
            try:
                runtime.stop("generation")
                progress = st.empty()
                report = build_snapshot(runtime, progress=lambda i, n, name: progress.text(f"{i + 1}/{n} {name}"))
                st.success(f"更新しました：{report['chunks']}チャンク")
            except Exception as exc:
                st.error(str(exc))
            finally:
                work_lock.release()
