"""Split page text into overlapping passages for retrieval.

Rules:
* A chunk never crosses a page boundary, so every chunk cites exactly one page.
* Chunks are packed from whole sentences up to `max_words`; a sentence longer than that is
  cut into word windows.
* Consecutive chunks share up to `overlap_words` of trailing sentences, so a fact that sits
  on a boundary is still found whole in one of them.

Words stand in for tokens (English is about 1.3 tokens per word), so 200 words stays far
below the embedding model's context limit.
"""

import re
from dataclasses import dataclass

CHUNKER_VERSION = "sent-v1"
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9(\"'\[])")


@dataclass(frozen=True)
class Chunk:
    index: int
    page: int  # 1-based
    text: str


def split_sentences(text: str, max_words: int) -> list[str]:
    flat = " ".join(text.split())
    sentences: list[str] = []
    for sentence in _SENTENCE_END.split(flat):
        words = sentence.split()
        for i in range(0, len(words), max_words):
            sentences.append(" ".join(words[i : i + max_words]))
    return [s for s in sentences if s]


def _overlap(sentences: list[str], overlap_words: int) -> list[str]:
    """The longest run of trailing sentences that fits in `overlap_words`."""
    kept: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        n = len(sentence.split())
        if total + n > overlap_words:
            break
        kept.insert(0, sentence)
        total += n
    return kept


def chunk_pages(pages: list[str], max_words: int, overlap_words: int) -> list[Chunk]:
    if overlap_words >= max_words:
        raise ValueError("overlap_words must be smaller than max_words")
    chunks: list[Chunk] = []
    for page_number, text in enumerate(pages, start=1):
        current: list[str] = []
        count = 0
        for sentence in split_sentences(text, max_words):
            n = len(sentence.split())
            if current and count + n > max_words:
                chunks.append(Chunk(len(chunks), page_number, " ".join(current)))
                current = _overlap(current, overlap_words)
                count = sum(len(s.split()) for s in current)
                if count + n > max_words:
                    current, count = [], 0
            current.append(sentence)
            count += n
        if current:
            chunks.append(Chunk(len(chunks), page_number, " ".join(current)))
    return chunks
