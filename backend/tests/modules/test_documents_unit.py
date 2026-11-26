"""PDF extraction limits and chunking rules (no database)."""

import io

import pytest
from pypdf import PdfWriter

from app.modules.documents.chunking import chunk_pages, split_sentences
from app.modules.documents.pdf import InvalidPdf, clean_text, extract_pages
from tests.pdf_factory import make_pdf


def test_extracts_text_per_page() -> None:
    pages = extract_pages(make_pdf(["Alpha policy text.", "Beta policy text."]), max_pages=5)
    assert pages == ["Alpha policy text.", "Beta policy text."]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"PK\x03\x04 not a pdf", "PDF header"),
        (make_pdf(["one", "two", "three"]), "limit is 2"),
        (make_pdf([""]), "No text found"),
        (b"%PDF-1.4\n garbage without objects", "readable PDF|no pages|No text"),
    ],
)
def test_rejects_bad_files(data: bytes, message: str) -> None:
    with pytest.raises(InvalidPdf, match=message):
        extract_pages(data, max_pages=2)


def test_rejects_encrypted_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("secret", algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(InvalidPdf, match="Encrypted"):
        extract_pages(out.getvalue(), max_pages=5)


def test_clean_text_removes_nul_and_control_characters() -> None:
    """Postgres text columns reject NUL bytes outright."""
    assert clean_text("ﬁne\x00 print\x07  here\n\n\nnext") == "fine print here\nnext"


def test_chunks_stay_on_one_page_and_respect_the_word_budget() -> None:
    page = " ".join(f"Sentence number {i} has six words." for i in range(30))
    chunks = chunk_pages([page, "Short second page."], max_words=40, overlap_words=12)
    assert all(len(c.text.split()) <= 40 for c in chunks)
    assert {c.page for c in chunks} == {1, 2}
    assert chunks[-1].text == "Short second page." and chunks[-1].page == 2
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_consecutive_chunks_overlap_by_whole_sentences() -> None:
    page = " ".join(f"Rule {i} applies here today." for i in range(20))
    first, second = chunk_pages([page], max_words=25, overlap_words=10)[:2]
    # 5-word sentences, so the 10-word overlap is exactly the last two sentences.
    assert first.text.endswith("Rule 3 applies here today. Rule 4 applies here today.")
    assert second.text.startswith("Rule 3 applies here today. Rule 4 applies here today.")


def test_long_sentence_is_cut_into_windows() -> None:
    sentence = " ".join(["word"] * 95)
    assert [len(s.split()) for s in split_sentences(sentence, 40)] == [40, 40, 15]


def test_overlap_must_be_smaller_than_chunk() -> None:
    with pytest.raises(ValueError):
        chunk_pages(["text"], max_words=10, overlap_words=10)
