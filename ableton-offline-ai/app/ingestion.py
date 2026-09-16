"""Structure-aware local parsing. Displayed source text is never executed as HTML."""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .settings import sha256


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)


def html_blocks(text):
    soup = BeautifulSoup(text, "html.parser")
    body = next((match for selector in (".js-manual-content", ".article-body", "article", "main")
                 if (match := soup.select_one(selector)) is not None), soup)
    for node in body.select("script, style, nav, footer, header, iframe, form, noscript"):
        node.decompose()
    headings = []
    anchor = ""
    for node in body.find_all(re.compile(r"^(h[1-6]|p|ul|ol|table|pre|figcaption)$")):
        if node.find_parent(["ul", "ol", "table", "pre"]):
            continue
        value = node.get_text(" ", strip=True)
        if not value:
            continue
        if re.fullmatch(r"h[1-6]", node.name):
            level = int(node.name[1])
            headings = [(n, t) for n, t in headings if n < level] + [(level, value)]
            anchor = node.get("id") or (node.find("a", id=True) or {}).get("id", "")
            continue
        if node.name in ("ol", "ul"):
            value = "\n".join(f"{i}. {li.get_text(' ', strip=True)}" for i, li in enumerate(node.find_all("li", recursive=False), 1))
        elif node.name == "table":
            value = "\n".join(" | ".join(c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])) for row in node.find_all("tr"))
        yield value, {"heading_path": [t for _, t in headings], "anchor": anchor, "block_type": node.name}


def pdf_blocks(path):
    import pdfplumber
    from pypdf import PdfReader
    reader = PdfReader(path)
    outline = []

    def walk(items, parents=()):
        previous = parents
        for item in items:
            if isinstance(item, list):
                walk(item, previous)
            else:
                previous = parents + (item.title,)
                try:
                    outline.append((reader.get_destination_page_number(item), list(previous)))
                except (ValueError, KeyError):
                    pass

    walk(reader.outline)
    outline.sort(key=lambda x: x[0])
    count = 0
    empty_pages = []
    with pdfplumber.open(path) as pdf:
        for n, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if not text.strip():
                empty_pages.append(n + 1)
                continue
            count += 1
            headings = next((h for p, h in reversed(outline) if p <= n), [])
            yield text, {"heading_path": headings, "pdf_page": n + 1,
                         "page_label": reader.page_labels[n], "block_type": "pdf",
                         "structure_quality": "outline" if headings else "page_only"}
    if not count:
        raise ValueError(f"画像だけのPDFです。OCRが必要です: {path.name}")
    if empty_pages:
        raise ValueError(f"文字のないページがあります。OCRまたは確認が必要です: {path.name} {empty_pages[:20]}")


def split_block(text, limit):
    """Sentence/line boundaries first; long tokens are split without silent truncation."""
    if len(text) <= limit:
        return [text]
    pieces, current = [], ""
    for line in re.split(r"(?<=[。.!?])\s+|\n", text):
        while len(line) > limit:
            if current:
                pieces.append(current)
                current = ""
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            pieces.append(line[:cut])
            line = line[cut:].lstrip()
        if len(current) + len(line) + 1 > limit and current:
            pieces.append(current)
            current = ""
        current = (current + "\n" + line).strip()
    if current:
        pieces.append(current)
    return pieces


def parse(path, metadata, limit=1100, overlap=120):
    path = Path(path)
    digest = sha256(path)
    doc_id = metadata.get("document_id", hashlib.sha256(str(path).encode()).hexdigest()[:16])
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        blocks = pdf_blocks(path)
    else:
        text = path.read_text(encoding="utf-8-sig")
        if suffix in (".html", ".htm"):
            blocks = html_blocks(text)
        elif suffix in (".md", ".markdown"):
            blocks = html_blocks(MarkdownIt("commonmark", {"html": False}).enable("table").render(text))
        elif suffix == ".txt":
            blocks = ((p, {"heading_path": [], "block_type": "text"}) for p in text.split("\n\n") if p.strip())
        else:
            raise ValueError(f"未対応の形式です: {suffix}")
    base = dict(metadata, document_id=doc_id, revision_id=digest, source_path=str(path.resolve()),
                format=suffix[1:], title=metadata.get("title", path.name), parser_version="1")
    chunks, current, last_meta = [], "", None

    def flush():
        nonlocal current
        if current:
            i = len(chunks)
            cid = hashlib.sha256(f"{doc_id}:{digest}:{i}:{current}".encode()).hexdigest()[:24]
            chunks.append(Chunk(cid, current, dict(base, **last_meta, chunk_index=i)))
            current = ""

    for text, block_meta in blocks:
        key = (block_meta.get("heading_path"), block_meta.get("pdf_page"), block_meta.get("anchor"))
        previous = None if last_meta is None else (last_meta.get("heading_path"), last_meta.get("pdf_page"), last_meta.get("anchor"))
        if key != previous:
            flush()
        for piece in split_block(text, limit):
            if current and len(current) + len(piece) + 2 > limit:
                tail = current[-overlap:] if overlap else ""
                flush()
                if tail and len(tail) + len(piece) + 2 <= limit:
                    current = tail
            last_meta = block_meta
            current = (current + "\n\n" + piece).strip()
    flush()
    for i, chunk in enumerate(chunks):
        chunk.metadata["previous_id"] = chunks[i - 1].id if i else None
        chunk.metadata["next_id"] = chunks[i + 1].id if i + 1 < len(chunks) else None
    if not chunks:
        raise ValueError(f"本文を抽出できません: {path.name}")
    return chunks


def discover(root):
    for sidecar in sorted(Path(root).rglob("*.meta.json")):
        metadata = json.loads(sidecar.read_text())
        path = sidecar.with_name(sidecar.name.removesuffix(".meta.json"))
        if metadata.get("index", True) and path.is_file():
            yield path, metadata
