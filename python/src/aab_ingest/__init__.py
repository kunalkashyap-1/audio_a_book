"""Bytes in, structured chapters out. Pure functions: no database, no network.

Supported at MVP: .txt, .md, .html, .epub. PDF and DOCX are deliberately absent rather
than half-working; they arrive with a proper parser and a licence review.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from aab_core import InvalidInput, normalise_text

PARSER_VERSION = "ingest-0.2"

_HEADING = re.compile(
    r"^\s{0,3}((?:chapter|part|book|act|section|epilogue|prologue)\b[^\n]{0,80})\s*$",
    re.IGNORECASE,
)
_ALL_CAPS = re.compile(r"^\s{0,3}([A-Z][A-Z0-9 '’\-]{2,58})\s*$")
_GUTENBERG_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)
_GUTENBERG_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)


@dataclass(frozen=True)
class Chapter:
    title: str
    text: str


@dataclass(frozen=True)
class ParsedBook:
    title: str | None
    language: str
    chapters: list[Chapter]
    parser_version: str = PARSER_VERSION

    @property
    def word_count(self) -> int:
        return sum(len(c.text.split()) for c in self.chapters)


def detect_format(filename: str, content: bytes) -> str:
    suffix = PurePosixPath(filename.lower()).suffix
    if suffix in {".pdf", ".docx", ".mobi", ".azw", ".azw3"}:
        raise InvalidInput(
            f"{suffix} is not supported yet. Convert to EPUB or TXT.")
    if content[:4] == b"PK\x03\x04" or suffix == ".epub":
        return "epub"
    if suffix in {".txt", ".md", ".markdown"}:
        return "text"
    if suffix in {".html", ".htm", ".xhtml"}:
        return "html"
    raise InvalidInput(f"unsupported format: {suffix or 'unknown'}")


def parse(filename: str, content: bytes, language: str = "en") -> ParsedBook:
    fmt = detect_format(filename, content)
    if fmt == "epub":
        return parse_epub(content, language)
    text = content.decode("utf-8", errors="replace")
    if fmt == "html":
        text = html_to_text(text)
    return ParsedBook(title=None, language=language,
                      chapters=split_chapters(normalise_text(text)))


# ---------------------------------------------------------------- text

def strip_gutenberg(text: str) -> str:
    start = _GUTENBERG_START.search(text)
    if start:
        text = text[start.end():]
    end = _GUTENBERG_END.search(text)
    if end:
        text = text[:end.start()]
    return text


def normalise(text: str) -> str:
    text = normalise_text(text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)        # de-hyphenate line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_heading(line: str) -> bool:
    if _HEADING.match(line):
        return True
    m = _ALL_CAPS.match(line)
    if m and len(line.strip()) <= 59 and not line.strip().endswith("."):
        # Reject all-caps sentences: headings rarely contain more than six words.
        return len(line.split()) <= 6
    return False


_ROMAN = re.compile(r"\b[IVXLCDM]{1,7}\b")
_ROMAN_TOKEN = re.compile(r"\b([ivxlcdm]{1,7})\b", re.I)
_ROMAN_VALID = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_HEADING_LEAD = re.compile(r"^(chapter|part|book|act|section|volume|letter|scene|canto)\b",
                           re.I)


def display_title(raw: str) -> str:
    """``CHAPTER IV`` → ``Chapter IV``; leave mixed-case titles untouched."""
    title = raw.strip()
    if not title.isupper():
        return title
    title = title.title()
    if not _HEADING_LEAD.match(title):
        return title
    def _numeral(match: re.Match[str]) -> str:
        token = match.group(1)
        upper = token.upper()
        return upper if _ROMAN_VALID.match(upper) else token
    return _ROMAN_TOKEN.sub(_numeral, title)


def split_chapters(text: str) -> list[Chapter]:
    text = strip_gutenberg(normalise(text))
    if not text:
        raise InvalidInput("document is empty")

    lines = text.split("\n")
    marks: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or not is_heading(stripped):
            continue
        # A heading sits at a paragraph boundary: start of file or after a blank line.
        # Without this, "Chapter IV" inside a sentence becomes a spurious split.
        if i == 0 or not lines[i - 1].strip():
            marks.append((i, stripped))

    # Too many "headings" means we are matching chapter references inside prose.
    # One or two headings are common (short stories, novellas), so the bar is low.
    plausible = 1 <= len(marks) <= max(400, len(text.split()) // 150)
    if plausible:
        chapters: list[Chapter] = []
        for idx, (line_no, title) in enumerate(marks):
            end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
            body = "\n".join(lines[line_no + 1:end]).strip()
            if len(body.split()) >= 12:
                chapters.append(Chapter(title=display_title(title), text=body))
        # Reject the split if it lost most of the book: a stray heading in the front
        # matter must not silently discard the body text.
        covered = sum(len(c.text.split()) for c in chapters)
        if chapters and covered >= 0.5 * len(text.split()):
            return chapters

    # No reliable structure: chunk on paragraph boundaries at ~4,000 words.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[Chapter] = []
    buf: list[str] = []
    words = 0
    for para in paragraphs:
        buf.append(para)
        words += len(para.split())
        if words >= 4000:
            chunks.append(Chapter(title=f"Part {len(chunks) + 1}", text="\n\n".join(buf)))
            buf, words = [], 0
    if buf:
        chunks.append(Chapter(title=f"Part {len(chunks) + 1}", text="\n\n".join(buf)))
    if not chunks:
        raise InvalidInput("no readable text found")
    return chunks


# ---------------------------------------------------------------- html

class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "section", "article", "tr", "td"}
    SKIP = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    return html.unescape("".join(parser.parts))


# ---------------------------------------------------------------- epub

def parse_epub(content: bytes, language: str = "en") -> ParsedBook:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise InvalidInput("not a valid EPUB archive") from exc

    names = set(archive.namelist())
    if "META-INF/container.xml" not in names:
        raise InvalidInput("EPUB is missing META-INF/container.xml")
    container = ET.fromstring(archive.read("META-INF/container.xml"))
    rootfile = _first_attr(container, "rootfile", "full-path")
    if not rootfile or rootfile not in names:
        raise InvalidInput("EPUB package document not found")

    opf = ET.fromstring(archive.read(rootfile))
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    title = _text(opf.find(".//opf:metadata/opf:title", ns)) or None
    base = PurePosixPath(rootfile).parent

    manifest: dict[str, str] = {}
    media_type: dict[str, str] = {}
    for item in opf.findall(".//opf:manifest/opf:item", ns):
        iid, href = item.get("id"), item.get("href")
        if iid and href:
            manifest[iid] = str(base / href) if base.name else href
            media_type[iid] = item.get("media-type", "")

    chapters: list[Chapter] = []
    for ref in opf.findall(".//opf:spine/opf:itemref", ns):
        iid = ref.get("idref")
        path = manifest.get(iid) if iid else None
        if not path or path not in names:
            continue
        if "html" not in media_type.get(iid, "html"):
            continue
        text = normalise(html_to_text(archive.read(path).decode("utf-8", "replace")))
        if len(text.split()) < 40:
            continue
        heading = _first_heading(archive.read(path).decode("utf-8", "replace"))
        chapters.append(Chapter(title=heading or f"Chapter {len(chapters) + 1}", text=text))

    if not chapters:
        raise InvalidInput("EPUB contains no readable chapters")
    return ParsedBook(title=title, language=language, chapters=chapters)


def _first_attr(tree, tag: str, attr: str) -> str | None:
    for element in tree.iter():
        if element.tag.endswith(tag) and element.get(attr):
            return element.get(attr)
    return None


def _text(element) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _first_heading(markup: str) -> str | None:
    m = re.search(r"<h[12][^>]*>(.*?)</h[12]>", markup, re.I | re.S)
    if not m:
        return None
    text = re.sub(r"<[^>]+>", "", m.group(1))
    return html.unescape(text).strip()[:200] or None
