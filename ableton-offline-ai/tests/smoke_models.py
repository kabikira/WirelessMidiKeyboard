"""Real model smoke/benchmark; executed explicitly, not in the unit-test suite."""
import json
import resource
import time
from app.offline import enable
enable()
from app.runtime import Runtime
from app.answer import SCHEMA, validate
from app.retrieval import Hit
from app.settings import ROOT, write_json

r = Runtime()
start = time.monotonic()
report = {}
try:
    v = r.embed("In Ableton Live, the Track switch enables MIDI notes.")
    report["embedding"] = {"dimensions": len(v), "norm": float(v @ v), "seconds": time.monotonic() - start}
    print(json.dumps(report), flush=True)
    source = "The Track switch enables Live to receive MIDI notes and MIDI CC messages. The Remote switch allows MIDI controllers to control mapped parameters."
    before = time.monotonic()
    result = r.generate([
        {"role": "system", "content": "Answer in Japanese ONLY from SOURCE 1. Return status=supported, claims with text, source=1 and an exact quote from SOURCE 1; missing empty. Give one brief claim."},
        {"role": "user", "content": "MIDIのTrackスイッチは何ですか？\nSOURCE 1: " + source}], SCHEMA)
    payload = json.loads(result["choices"][0]["message"]["content"])
    validate(payload, [Hit("test", source, {})])
    report["generation"] = {"seconds": time.monotonic() - before, "usage": result.get("usage"), "answer": payload}
    report["python_external_network_guard"] = True
    print(json.dumps(report, ensure_ascii=False), flush=True)
finally:
    r.close()
    report["max_child_rss_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    write_json(ROOT / "evaluations/model-smoke.json", report)
