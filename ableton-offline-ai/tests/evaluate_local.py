"""Small transparent smoke corpus, NOT a substitute for the planned held-out evaluation."""
from dataclasses import asdict
import json
import time
from app.offline import enable
enable()
from app.answer import answer_question
from app.retrieval import Retriever
from app.runtime import Runtime
from app.settings import ROOT, write_json

CASES = [
    ("SimplerのClassicモードとは？", "Simpler"),
    ("Samplerで複数のサンプルをキーに割り当てるには？", "Sampler"),
    ("Operatorのアルゴリズムについて教えて", "Operator"),
    ("Wavetableのオシレーターについて教えて", "Wavetable"),
    ("EchoのDry/Wetとは何ですか？", "Echo"),
    ("Compressorのサイドチェインについて", "Compressor"),
    ("MIDIエフェクトArpeggiatorの使い方", "Arpeggiator"),
    ("MIDIのTrackスイッチとRemoteスイッチの違いは？", "MIDI"),
    ("Audio Fromで外部入力を選ぶには？", "Routing"),
    ("MonitorのInとAutoとOffの違いは？", "Monitoring"),
    ("ギターを録音するときの入力とモニタリング", "Routing"),
    ("External Instrumentで外部シンセを使うには？", "External Instrument"),
    ("Max for Liveとは何ですか？", "Max"),
    ("WarpモードのBeatsとは？", "Beats"),
    ("ReturnトラックとSendについて", "Mixing"),
]

runtime = Runtime()
raw_outputs = []
generate = runtime.generate
def record_generate(messages, schema):
    result = generate(messages, schema)
    raw_outputs.append(result)
    return result
runtime.generate = record_generate
retriever = Retriever()
report = {"snapshot": retriever.snapshot.name, "scope": "smoke-only; heading relevance, not factual accuracy", "retrieval": [], "answers": []}
try:
    for question, expected in CASES:
        start = time.monotonic()
        hits = retriever.search(question, runtime=runtime)
        headings = [" > ".join(h.metadata["heading_path"]) for h in hits]
        ok = any(expected.lower() in h.lower() for h in headings)
        report["retrieval"].append({"question": question, "expected_heading": expected, "found": ok, "headings": headings,
                                   "similarities": [h.similarity for h in hits], "seconds": time.monotonic() - start})
        print("retrieval", ok, question, flush=True)
    for question in ["MIDIのTrackスイッチとRemoteスイッチの違いは？", "EchoのDry/Wetとは何ですか？", "LiveのQuantum Bananaボタンを押して月の重力を変更する手順を教えて"]:
        print("answer", question, flush=True)
        result = answer_question(question, retriever, runtime)
        entry = {"question": question, "result": asdict(result), "raw_outputs": raw_outputs.copy()}
        raw_outputs.clear()
        report["answers"].append(entry)
        write_json(ROOT / "evaluations/local-smoke.json", report)
        print(json.dumps({"status": result.status, "reason": result.reason, "claims": result.claims, "seconds": result.seconds}, ensure_ascii=False), flush=True)
finally:
    runtime.close()
    write_json(ROOT / "evaluations/local-smoke.json", report)
