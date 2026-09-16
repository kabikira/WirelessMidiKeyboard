"""Explicit online acquisition only. Never imported by the answering path."""
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

from .settings import ROOT, sha256, write_json

HOSTS = {"www.ableton.com", "help.ableton.com", "docs.cycling74.com", "cdn-resources.ableton.com", "cdn-downloads.ableton.com"}


def check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.port not in (None, 443):
        raise ValueError("公式資料の許可済みHTTPS URLだけ取得できます。")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    check_url(url)
    opener = urllib.request.build_opener(SafeRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "AbletonOfflinePersonalReference/0.1"})
    with opener.open(request, timeout=60) as response:
        data = response.read(40 * 1024 * 1024 + 1)
        if len(data) > 40 * 1024 * 1024:
            raise ValueError("資料が40MBを超えています。手動取り込みを使用してください。")
        return data, response.url


def update_manual(major=12, progress=print):
    if major not in (11, 12):
        raise ValueError("対応するLiveメジャー版は11と12です。")
    base = f"https://www.ableton.com/en/live-manual/{major}/"
    index, _ = fetch(base)
    soup = BeautifulSoup(index, "html.parser")
    urls = sorted({urllib.parse.urljoin(base, a["href"]).split("#")[0] for a in soup.select("a[href]")
                   if urllib.parse.urljoin(base, a["href"]).startswith(base)})
    urls = [u for u in urls if u.rstrip("/") != base.rstrip("/")]
    if not urls:
        raise ValueError("マニュアルの章一覧を取得できません。既存資料を維持します。")
    now = datetime.now(timezone.utc).isoformat()
    stage = ROOT / "updates/staging" / (now.replace(":", "-") + f"-live{major}")
    stage.mkdir(parents=True)
    target = ROOT / f"knowledge/ableton/live-{major}"
    target.mkdir(parents=True, exist_ok=True)
    collected = []
    for i, url in enumerate(urls):
        progress(f"[{i + 1}/{len(urls)}] {url}")
        data, final_url = fetch(url)
        page = BeautifulSoup(data, "html.parser")
        main = page.select_one(".js-manual-content")
        if main is None or main.find("h1") is None:
            raise ValueError("本文構造が変わっています。既存資料は更新しません。")
        slug = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]
        path = stage / (slug + ".html")
        path.write_bytes(data)
        meta = {"document_id": f"ableton-live-{major}-{slug}", "canonical_id": f"live-{major}-{slug}",
                "title": f"Ableton Live {major} Manual — {main.h1.get_text(' ', strip=True)}",
                "publisher": "Ableton", "language": "en", "url": final_url,
                "live_major": major, "version_scope": "major_only", "source_type": "official_manual",
                "retrieved_at": now, "sha256": sha256(path), "verified": False}
        write_json(path.with_name(path.name + ".meta.json"), meta)
        collected.append(path)
        time.sleep(0.3)
    # Acquisition completes before changing the current source set; indexes switch separately.
    import shutil
    for path in collected:
        shutil.copy2(path, target / path.name)
        shutil.copy2(path.with_name(path.name + ".meta.json"), target / (path.name + ".meta.json"))
    write_json(stage / "manifest.json", {"urls": urls, "retrieved_at": now, "count": len(collected)})
    return len(collected)


def add_official(url, category="max_for_live", live_major=None, exact_version=None):
    if category not in ("max_for_live", "ableton/knowledge-base", "ableton/release-notes"):
        raise ValueError("未対応の資料分類です。")
    data, final_url = fetch(url)
    soup = BeautifulSoup(data, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    declared = re.search(r"This document refers to Ableton Live version\s+(\d+(?:\.\d+){1,2})", soup.get_text(" ", strip=True), re.I)
    if declared:
        if exact_version and exact_version != declared[1]:
            raise ValueError("指定版と資料に明記された版が異なります。既存資料を維持します。")
        exact_version = declared[1]
        live_major = int(exact_version.split(".")[0])
    path = ROOT / "knowledge" / category / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    meta = {"document_id": hashlib.sha256(url.encode()).hexdigest()[:16], "title": title,
            "url": final_url, "publisher": urllib.parse.urlsplit(final_url).hostname,
            "source_type": "official", "language": "en", "live_major": live_major,
            "version_scope": "major_only" if live_major else "unknown",
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "sha256": sha256(path)}
    if exact_version:
        # Only supply when the source explicitly declares this version.
        meta.update(live_major=int(exact_version.split(".")[0]), live_min=exact_version, live_max=exact_version, version_scope="exact")
    write_json(path.with_name(path.name + ".meta.json"), meta)
    return path
