import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .settings import ROOT, data_root, settings, sha256, write_json


def main():
    parser = argparse.ArgumentParser(description="Ableton Offline AI")
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser("update", help="明示的にオンラインで公式マニュアルを取得")
    update.add_argument("--major", type=int, choices=[11, 12], default=12)
    add = sub.add_parser("fetch", help="明示的に公式HTML資料を取得")
    add.add_argument("url")
    add.add_argument("--category", default="max_for_live")
    add.add_argument("--major", type=int)
    add.add_argument("--exact-version")
    ingest = sub.add_parser("ingest", help="保存済み資料だけから索引を作成")
    ingest.add_argument("--lexical-only", action="store_true")
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--search-only", action="store_true")
    ask.add_argument("--version", default=settings()["profile"]["live_version"])
    restore = sub.add_parser("restore")
    restore.add_argument("snapshot")
    sub.add_parser("doctor")
    sub.add_parser("ui")
    args = parser.parse_args()
    if args.command == "update":
        from .update import update_manual
        print(f"取得完了: {update_manual(args.major)}章。次にingestを実行してください。")
        return
    if args.command == "fetch":
        from .update import add_official
        print(add_official(args.url, args.category, args.major, args.exact_version))
        return
    from .offline import enable
    enable()
    if args.command == "ui":
        from streamlit.web import cli as stcli
        sys.argv = ["streamlit", "run", str(ROOT / "ui.py"), "--server.address=127.0.0.1",
                    "--browser.gatherUsageStats=false", "--server.headless=true", "--server.fileWatcherType=none"]
        stcli.main()
        return
    from .store import activate, build_snapshot, current_snapshot
    from .runtime import Runtime
    if args.command == "restore":
        activate(args.snapshot)
        print("snapshotを切り替えました。")
        return
    if args.command == "doctor":
        results = {}
        manifest_path = ROOT / "models/manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        for kind in ("generation", "embedding"):
            path = ROOT / settings()["runtime"][f"{kind}_model"]
            results[kind] = {"exists": path.exists(), "sha256_ok": path.exists() and sha256(path) == manifest.get(kind, {}).get("sha256")}
        try:
            snapshot = current_snapshot()
            snap_manifest = json.loads((snapshot / "manifest.json").read_text())
            results["snapshot"] = {"id": snapshot.name, "sha256_ok": sha256(snapshot / "knowledge.sqlite") == snap_manifest["database_sha256"], "chunks": snap_manifest["chunks"]}
        except FileNotFoundError as exc:
            results["snapshot"] = {"error": str(exc)}
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    runtime = Runtime()
    try:
        if args.command == "ingest":
            report = build_snapshot(None if args.lexical_only else runtime,
                                    progress=lambda i, n, name: print(f"[{i + 1}/{n}] {name}", flush=True))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "ask":
            from .retrieval import Retriever
            retriever = Retriever()
            if args.search_only:
                result = [asdict(h) for h in retriever.search(args.question, args.version)]
            else:
                from .answer import answer_question
                result = asdict(answer_question(args.question, retriever, runtime, args.version))
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
