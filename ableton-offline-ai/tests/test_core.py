import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

from app.answer import validate, answer_question, evidence_catalog, select_claims
from app.ingestion import parse
from app.retrieval import Hit, Retriever, applicable, sampling_overview, introductory
from app.settings import write_json
from app.store import activate, build_snapshot, current_snapshot
from app.update import check_url


def source(tmp_path, name="routing.md", major=12, text=None):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "# Routing\n\n## Monitoring\n\nMonitoring passes the input signal to the output. Select In to hear input.\n\n## MIDI\n\nThe Track switch enables MIDI notes. Remote controls mapped parameters.")
    meta = {"document_id": name, "title": name, "live_major": major, "version_scope": "major_only"}
    write_json(path.with_name(name + ".meta.json"), meta)
    return path, meta


def test_html_selects_body_not_navigation(tmp_path):
    path, meta = source(tmp_path, "manual.html", text='<main><nav>WRONG</nav><section class="js-manual-content"><h1 id="a">1. Routing</h1><h2 id="b">1.1 Monitoring</h2><p>Correct source.</p><script>BAD()</script></section><ul><li>TOC GARBAGE</li></ul></main>')
    chunks = parse(path, meta)
    assert len(chunks) == 1
    assert chunks[0].text == "Correct source."
    assert chunks[0].metadata["heading_path"] == ["1. Routing", "1.1 Monitoring"]
    assert chunks[0].metadata["anchor"] == "b"


def test_sections_never_merge_and_have_stable_ids(tmp_path):
    path, meta = source(tmp_path)
    a = parse(path, meta)
    b = parse(path, meta)
    assert [c.id for c in a] == [c.id for c in b]
    assert len(a) == 2
    assert a[0].metadata["heading_path"] == ["Routing", "Monitoring"]
    assert "Remote" not in a[0].text
    path.write_text(path.read_text() + "\nChanged.")
    assert parse(path, meta)[0].id != a[0].id


def test_long_japanese_text_not_silently_truncated(tmp_path):
    value = "音声入力の設定を確認します。" * 300
    path, meta = source(tmp_path, "note.txt", text=value)
    chunks = parse(path, meta, limit=200, overlap=0)
    assert all(len(c.text) <= 200 for c in chunks)
    assert "".join(c.text for c in chunks) == value


def test_pdf_blank_fails_instead_of_inventing_text(tmp_path):
    from pypdf import PdfWriter
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.write(path)
    with pytest.raises(ValueError, match="OCR"):
        parse(path, {"title": "scan"})


def test_pdf_text_outline_and_page_citations(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    for text in ("Routing input and output.", "Monitoring listens to the input."):
        page = writer.add_blank_page(400, 400)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 30 350 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    parent = writer.add_outline_item("Routing", 0)
    writer.add_outline_item("Monitoring", 1, parent=parent)
    path = tmp_path / "manual.pdf"
    writer.write(path)
    chunks = parse(path, {"title": "Example manual"})
    assert [c.metadata["pdf_page"] for c in chunks] == [1, 2]
    assert [c.metadata["page_label"] for c in chunks] == ["1", "2"]
    assert chunks[1].metadata["heading_path"] == ["Routing", "Monitoring"]
    assert chunks[1].text == "Monitoring listens to the input."


@pytest.mark.parametrize("meta,version,expected", [
    ({"live_major": 12}, "11.3", False),
    ({"live_major": 12}, "12.3.5", True),
    ({"live_major": 12, "live_min": "12.4"}, "12.3.5", False),
    ({"live_major": 12, "live_max": "12.3.5"}, "12.4", False),
    ({"live_major": 12, "editions": ["Standard"]}, "12.3.5", False),
])
def test_version_filter(meta, version, expected):
    assert applicable(meta, version, "Suite") is expected


def test_snapshot_atomic_failure_and_restore(tmp_path):
    knowledge, data = tmp_path / "knowledge", tmp_path / "data"
    source(knowledge)
    first = build_snapshot(knowledge=knowledge, root=data)
    snap = current_snapshot(data)
    assert first["chunks"] == 2
    assert list((snap / "originals").iterdir())
    bad, _ = source(knowledge, "bad.html", text="<script>nothing</script>")
    with pytest.raises(ValueError):
        build_snapshot(knowledge=knowledge, root=data)
    assert current_snapshot(data) == snap
    bad.write_text("<p>Recovered content.</p>")
    second = build_snapshot(knowledge=knowledge, root=data)
    assert second["snapshot"] != first["snapshot"]
    activate(first["snapshot"], root=data)
    assert current_snapshot(data) == snap
    (snap / "knowledge.sqlite").write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        activate(first["snapshot"], root=data)


def test_search_filters_before_ranking(tmp_path):
    knowledge, data = tmp_path / "knowledge", tmp_path / "data"
    source(knowledge, "v11.md", major=11)
    source(knowledge, "v12.md", major=12)
    build_snapshot(knowledge=knowledge, root=data)
    retriever = Retriever(current_snapshot(data))
    hits = retriever.search("MIDI Track", "12.3.5")
    assert hits
    assert all(h.metadata["live_major"] == 12 for h in hits)
    assert retriever.search("zzzzunfindable") == []
    assert isinstance(retriever.search('" OR * DROP TABLE'), list)


def test_vector_reuse(tmp_path, monkeypatch):
    import app.store as store
    monkeypatch.setattr(store, "embedding_identity", lambda: "test-embedding")
    class FakeRuntime:
        calls = 0
        def embed(self, text):
            self.calls += 1
            return np.ones(1024, dtype=np.float32) / 32
    runtime = FakeRuntime()
    knowledge, data = tmp_path / "knowledge", tmp_path / "data"
    source(knowledge)
    first = build_snapshot(runtime, knowledge, data)
    assert runtime.calls == first["chunks"]
    second = build_snapshot(runtime, knowledge, data)
    assert second["reused_vectors"] == first["chunks"]
    assert runtime.calls == first["chunks"]


def valid_payload():
    return {"status": "supported", "claims": [{"text": "TrackはMIDIノートを有効にします。", "source": 1, "quote": "The Track switch enables MIDI notes."}], "missing": ""}


def test_citations_require_existing_id_and_exact_quote():
    hits = [Hit("id", "The Track switch enables MIDI notes.", {})]
    assert validate(valid_payload(), hits)
    payload = valid_payload()
    payload["claims"][0]["source"] = 99
    with pytest.raises(ValueError, match="引用"):
        validate(payload, hits)
    payload = valid_payload()
    payload["claims"][0]["quote"] = "The Track switch automatically mixes audio."
    with pytest.raises(ValueError, match="原文"):
        validate(payload, hits)
    payload = valid_payload()
    payload["claims"][0]["text"] = "![tracking](https://example.com)"
    with pytest.raises(ValueError):
        validate(payload, hits)


@pytest.mark.parametrize("query", ["Live 11の操作", "質問はLive 12.2の操作です", "Live 12.3.4では？"])
def test_requested_version_must_match_profile_before_search(query):
    result = answer_question(query, None, None, version="12.3.5")
    assert result.status == "unknown"
    assert "設定が異なります" in result.reason


def test_evidence_ids_reconstruct_only_existing_source_text():
    hits = [Hit("a", "Samples can be dragged into Simpler from the browser. Select Classic mode to play pitched samples.", {})]
    catalog = evidence_catalog(hits)
    claims = select_claims({"status": "supported", "evidence_ids": ["S1E1", "S1E2"]}, catalog)
    assert len(claims) == 2
    assert all(c["quote"] in hits[c["source"] - 1].text for c in claims)
    with pytest.raises(ValueError, match="根拠ID"):
        select_claims({"status": "supported", "evidence_ids": ["S99E99"]}, catalog)


def test_general_sampling_scope_does_not_override_specific_requests():
    assert sampling_overview("サンプリングの方法をおしえて\n\n")
    assert not sampling_overview("ギターを録音してサンプリングする方法")
    assert introductory("simplerの使い方をおしえて", ["Simpler"])
    assert not introductory("SimplerのWarpの使い方", ["Simpler"])


def test_introduction_keeps_loading_steps_under_shared_heading(tmp_path):
    knowledge, data = tmp_path / "knowledge", tmp_path / "data"
    text = "# Instruments\n\n## Simpler\n\nSimpler is a sampler instrument.\n\n" + "General description. " * 60 + "\n\nSamples can be dragged into Simpler from the browser.\n\n### Context Menu\n\nSimpler uses constant-power fades by default."
    source(knowledge, "live-instrument-reference.md", text=text)
    build_snapshot(knowledge=knowledge, root=data)
    hits = Retriever(current_snapshot(data)).search("simplerの使い方をおしえて", top_k=3)
    assert any("Samples can be dragged" in h.text for h in hits)
    assert all("Context Menu" not in h.metadata["heading_path"] for h in hits[:2])


def test_updated_source_uses_its_declared_version(tmp_path, monkeypatch):
    import app.update as updater
    url = "https://docs.cycling74.com/apiref/lom/"
    monkeypatch.setattr(updater, "ROOT", tmp_path)
    monkeypatch.setattr(updater, "fetch", lambda _: (b"<title>LOM</title><p>This document refers to Ableton Live version 12.4.1</p>", url))
    path = updater.add_official(url)
    meta = json.loads(path.with_name(path.name + ".meta.json").read_text())
    assert meta["live_min"] == meta["live_max"] == "12.4.1"
    assert meta["live_major"] == 12
    with pytest.raises(ValueError, match="指定版"):
        updater.add_official(url, exact_version="12.3.5")


@pytest.mark.parametrize("url", ["http://www.ableton.com/", "https://evil.example/", "https://www.ableton.com.evil.example/", "https://user@www.ableton.com/", "https://www.ableton.com:8000/"])
def test_updater_restricts_sources(url):
    with pytest.raises(ValueError):
        check_url(url)


def test_external_network_denied_before_connection():
    code = '''
from app.offline import enable
enable()
import socket
for op in [lambda: socket.getaddrinfo("example.com",443), lambda: socket.socket().connect(("1.1.1.1",443)), lambda: socket.socket(socket.AF_INET,socket.SOCK_DGRAM).sendto(b"x",("8.8.8.8",53))]:
    try: op()
    except PermissionError: pass
    else: raise AssertionError("network was not denied")
'''
    subprocess.run([sys.executable, "-c", code], check=True)


def test_imports_do_not_download_or_start_servers():
    code = '''
from app.offline import enable
enable()
import app.answer, app.retrieval, app.ingestion, app.store, app.runtime
'''
    subprocess.run([sys.executable, "-c", code], check=True)
