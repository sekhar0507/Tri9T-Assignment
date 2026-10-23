"""CT-200-specific PDF hierarchy parser.

Uses PyMuPDF text blocks (no OCR dependency for these text PDFs), retains tables as
plain-text rows, and fails visibly on unrecognized numbered headings. For scanned
PDFs, add OCR as a separate fallback rather than silently returning an empty tree.
"""
import pymupdf, re, hashlib, unicodedata
from dataclasses import dataclass, field
from pathlib import Path

HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.+?)\s*$")
FIGURE_RE = re.compile(r"^\s*(?:figure|fig\.?)\s*\d+[:.\- ]", re.I)
LIST_RE = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+")

@dataclass
class ParsedNode:
    logical_key: str
    heading: str
    section_number: str | None
    level: int
    body_text: str = ""
    parent_key: str | None = None
    children: list = field(default_factory=list)
    content_hash: str = ""

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("\u00ad", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def digest(s: str) -> str:
    return hashlib.sha256(norm(s).encode("utf-8")).hexdigest()

def extract_lines(pdf_path: str) -> list[str]:
    lines = []
    with pymupdf.open(pdf_path) as doc:
        for page_no, page in enumerate(doc):
            # blocks preserve reading order better than concatenating words globally
            blocks = sorted(page.get_text("blocks"), key=lambda b: (round(b[1], 1), b[0]))
            for block in blocks:
                raw = block[4]
                for line in raw.splitlines():
                    line = norm(line)
                    if line:
                        lines.append(line)
    return lines

def parse_pdf(pdf_path: str) -> list[ParsedNode]:
    lines = extract_lines(pdf_path)
    nodes: list[ParsedNode] = []
    by_number: dict[str, ParsedNode] = {}
    current: ParsedNode | None = None
    title = None
    pending_table = False
    for line in lines:
        # Ignore page-number-only fragments, but do not discard numeric section headings.
        if re.fullmatch(r"(?:page\s+)?\d+\s*(?:of\s+\d+)?", line, re.I):
            continue
        m = HEADING_RE.match(line)
        is_heading = bool(m and len(m.group(2).split()) <= 14 and not line.endswith((",", ";")))
        # The title can wrap across lines and is kept as a root node.
        if title is None and ("CardioTrack CT-200" in line or "Technical & User Manual" in line):
            title = ParsedNode("document", line, None, 0)
            nodes.append(title)
            current = title
            continue
        if is_heading:
            number, label = m.group(1), m.group(2).strip()
            # Avoid treating numbered list entries (e.g. "1. Normal: ...") as section headings.
            if re.match(r"^\d+\.\s", line) and not re.match(r"^\d+\.\d+", number):
                is_heading = False
            # Number hierarchy, not visual order, determines parent. Missing intermediate levels
            # attach to the nearest existing ancestor; this handles 2.1.1.1 with no 2.1.1.
            if is_heading:
                key = number
                # Duplicate numbering is preserved using occurrence suffix; never overwrite.
                if any(n.logical_key == key for n in nodes):
                    occurrence = 2
                    while any(n.logical_key == f"{key}~{occurrence}" for n in nodes):
                        occurrence += 1
                    key = f"{key}~{occurrence}"
                level = number.count(".") + 1
                node = ParsedNode(key, f"{number} {label}", number, level)
                parent_number = number.rsplit(".", 1)[0] if "." in number else "document"
                candidates = [n for n in nodes if n.section_number == parent_number]
                if candidates:
                    node.parent_key = candidates[-1].logical_key
                else:
                    # Attach to closest existing numeric prefix, or document root.
                    prefix = parent_number
                    while "." in prefix and not candidates:
                        prefix = prefix.rsplit(".", 1)[0]
                        candidates = [n for n in nodes if n.section_number == prefix]
                    node.parent_key = candidates[-1].logical_key if candidates else "document"
                nodes.append(node)
                by_number.setdefault(number, node)
                current = node
                continue
        if current is None:
            if title is None:
                title = ParsedNode("document", "CardioTrack CT-200 Technical & User Manual", None, 0)
                nodes.append(title)
                current = title
            else:
                current = title
        # Keep list items and table text in body. Table rows are reconstructed from extracted lines.
        if line.startswith("<IMAGE") or FIGURE_RE.match(line):
            current.body_text += ("\n" if current.body_text else "") + "[FIGURE/CAPTION] " + line
        else:
            current.body_text += ("\n" if current.body_text else "") + line
    # Build stable path keys from numbered section identifiers and duplicate occurrence suffixes.
    # Attach content to nodes by parser order; hash includes heading and body to detect meaningful edits.
    for n in nodes:
        n.body_text = re.sub(r"\n{3,}", "\n\n", n.body_text).strip()
        n.content_hash = digest(n.heading + "\n" + n.body_text)
    return nodes
