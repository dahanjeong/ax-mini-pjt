"""RAG retriever: place-profile sentences in an in-memory vector store.

A place profile is split into short sentences (documents); each sentence keeps a
`doc_id` (`<place_key>#<n>`) so a match can be shown with the exact evidence it
came from. The store lives only for one matching run (no DB).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

EmbedFn = Callable[[list[str]], list[list[float]]]

MAX_SENTENCE_CHARS = 200


@dataclass(frozen=True)
class Document:
    doc_id: str
    owner: str       # place_key the sentence belongs to
    text: str
    kind: str        # name | category | description | setting | facility | review


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+|(?<=다\.)", text or "")
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip(" .")
        if len(p) >= 4:
            out.append(p[:MAX_SENTENCE_CHARS])
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class VectorStore:
    """Documents + their vectors; `search` returns (doc, score) by cosine similarity."""
    docs: list[Document] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)

    @classmethod
    def build(cls, docs: list[Document], vectors: list[list[float]]) -> "VectorStore":
        if len(docs) != len(vectors):
            raise ValueError("one vector per document is required")
        return cls(list(docs), [list(v) for v in vectors])

    def search(self, query_vec: list[float], *, owner: Optional[str] = None,
               k: int = 2) -> list[tuple[Document, float]]:
        scored = [(d, cosine(query_vec, v)) for d, v in zip(self.docs, self.vectors)
                  if owner is None or d.owner == owner]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]
