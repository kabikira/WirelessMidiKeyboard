"""Local-only regression replay. Private questions/results stay under ignored data/."""
from dataclasses import asdict
import json
from app.offline import enable
enable()
from app.answer import answer_question
from app.retrieval import Retriever
from app.runtime import Runtime
from app.settings import data_root, write_json


def main():
    records = [json.loads(p.read_text()) for p in sorted((data_root() / "history").glob("*.json"))]
    cases = [(r["question"], r.get("version", "12.3.5"), True) for r in records]
    cases += [("EchoのDry/Wetとは何ですか？", "12.3.5", True),
              ("LiveのQuantum Bananaボタンで月の重力を変更するには？", "12.3.5", False)]
    report = []
    runtime = Runtime()
    try:
        retriever = Retriever()
        for question, version, expected_answer in cases:
            result = answer_question(question, retriever, runtime, version)
            ok = bool(result.claims) == expected_answer
            report.append({"question": question, "passed": ok, "result": asdict(result)})
            write_json(data_root() / "diagnostics/history-regression.json", report)
            print(json.dumps({"question": question, "passed": ok, "status": result.status,
                              "reason": result.reason, "claims": result.claims, "seconds": result.seconds}, ensure_ascii=False), flush=True)
    finally:
        runtime.close()
    if not all(r["passed"] for r in report):
        raise SystemExit("回答の回帰試験で失敗しました。data/diagnosticsを確認してください。")


if __name__ == "__main__":
    main()
