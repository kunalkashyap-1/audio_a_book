from __future__ import annotations

import io
import zipfile

import pytest

from aab_core import InvalidInput
from aab_ingest import (detect_format, display_title, html_to_text, parse, split_chapters,
                        strip_gutenberg)

SAMPLE = """CHAPTER I

It was a bright cold day in April, and the clocks were striking thirteen. The wind was
sharp and the air was clear, and the town below the hill looked smaller than it had.

CHAPTER II

The road ran north for three miles before it turned, and by then the rain had started.
Nobody spoke for a while, which was unusual, and the silence did most of the talking.
"""


def test_detects_formats(tmp_path) -> None:
    assert detect_format("book.txt", b"hello") == "text"
    assert detect_format("book.md", b"# hi") == "text"
    assert detect_format("book.html", b"<p>hi</p>") == "html"
    assert detect_format("book.epub", b"PK\x03\x04rest") == "epub"
    with pytest.raises(InvalidInput):
        detect_format("book.pdf", b"%PDF-1.7")
    with pytest.raises(InvalidInput):
        detect_format("book.docx", b"PK\x03\x04word")


def test_chapters_from_headings() -> None:
    chapters = split_chapters(SAMPLE)
    assert [c.title for c in chapters] == ["Chapter I", "Chapter II"]
    assert "striking thirteen" in chapters[0].text
    assert "The road ran north" in chapters[1].text


def test_two_chapter_book_is_not_collapsed() -> None:
    """Regression: requiring three headings turned a novella into one blob called "Part 1"."""
    chapters = split_chapters(SAMPLE)
    assert len(chapters) == 2
    assert not chapters[0].title.startswith("Part")


def test_chapter_reference_inside_prose_is_not_a_heading() -> None:
    text = (
        "The letter arrived on a Tuesday, and it said that Chapter IV had been removed by\n"
        "the censor, which annoyed everyone at the office for the rest of the week.\n\n"
        + "More prose follows here, with no heading at all. " * 20
    )
    chapters = split_chapters(text)
    assert len(chapters) == 1
    assert "Chapter IV had been removed" in chapters[0].text


def test_gutenberg_boilerplate_is_stripped() -> None:
    text = (
        "Some front matter.\n\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK FOO ***\n\n"
        + SAMPLE
        + "\n*** END OF THE PROJECT GUTENBERG EBOOK FOO ***\n\nlicence text"
    )
    chapters = split_chapters(text)
    assert "Some front matter" not in chapters[0].text
    assert "licence text" not in chapters[-1].text
    assert len(chapters) == 2


def test_unstructured_text_is_chunked() -> None:
    paragraph = "Sentence number one stands here. Sentence number two follows it closely. "
    body = "\n\n".join([paragraph * 40] * 12)
    chapters = split_chapters(body)
    assert len(chapters) >= 2
    assert all(c.title.startswith("Part ") for c in chapters)
    assert sum(len(c.text.split()) for c in chapters) > 3000


def test_parse_text_file() -> None:
    book = parse("sample.txt", SAMPLE.encode())
    assert book.word_count > 40
    assert len(book.chapters) == 2
    assert book.parser_version.startswith("ingest-")


def test_parse_html() -> None:
    markup = (
        "<html><head><title>t</title><style>p{color:red}</style></head><body>"
        "<h1>CHAPTER I</h1><p>" + SAMPLE.split("CHAPTER I")[1][:400] + "</p></body></html>"
    )
    book = parse("sample.html", markup.encode())
    assert "color:red" not in book.chapters[0].text
    assert len(book.chapters) >= 1


def test_html_to_text_drops_scripts() -> None:
    text = html_to_text("<p>Hello</p><script>alert('x')</script><p>World</p>")
    assert "alert" not in text
    assert "Hello" in text and "World" in text


def test_epub_round_trip() -> None:
    container = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
        "<metadata><title>Test Book</title></metadata><manifest>"
        '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
        "</manifest><spine>"
        '<itemref idref="c1"/><itemref idref="c2"/></spine></package>'
    )
    body = "word " * 120
    c1 = f"<html><body><h1>One</h1><p>{body}</p></body></html>"
    c2 = f"<html><body><h1>Two</h1><p>{body}</p></body></html>"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/c1.xhtml", c1)
        archive.writestr("OEBPS/c2.xhtml", c2)

    book = parse("test.epub", buffer.getvalue())
    assert book.title == "Test Book"
    assert [c.title for c in book.chapters] == ["One", "Two"]


def test_epub_without_container_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("random.txt", "nothing here")
    with pytest.raises(InvalidInput):
        parse("broken.epub", buffer.getvalue())


def test_empty_document_is_rejected() -> None:
    with pytest.raises(InvalidInput):
        split_chapters("   \n\n  \n")


@pytest.mark.parametrize("raw,expected", [
    ("CHAPTER I", "Chapter I"),
    ("CHAPTER II", "Chapter II"),
    ("CHAPTER XIV", "Chapter XIV"),
    ("PART ONE", "Part One"),
    ("The Orchard", "The Orchard"),
])
def test_display_title(raw: str, expected: str) -> None:
    assert display_title(raw) == expected


def test_strip_gutenberg_is_idempotent() -> None:
    text = "body only"
    assert strip_gutenberg(strip_gutenberg(text)) == text
