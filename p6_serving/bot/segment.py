"""Matching long messages by their question sentence (Phase C item 14).

A long message often has a story around one question ("I run a small business in Pune ... so does the file include every field?"). The story's words dilute the match and
count as unknown words. This module splits a long message into sentences and clauses and scores the pieces that look like questions separately.

Variants (set on SegmentMatcher.variant):
  none   the whole message only (the earlier behaviour)
  last   the last question piece only
  qmax   the best score per entry over the question pieces
  allmax the best score per entry over the whole message and every piece
"""
from __future__ import annotations

import re

LONG_WORDS = 12
MIN_PIECE = 3
LEADIN = (r"(?:so\s+|and\s+|but\s+)?(?:my\s+question\s+is|the\s+question\s+is|i\s+(?:just\s+)?(?:want|wanna|need)\s+to\s+know|i\s+was\s+wondering|"
          r"can\s+you\s+tell\s+me|could\s+you\s+tell\s+me|please\s+(?:tell|explain)|i\s+would\s+like\s+to\s+understand|i\s+just\s+wanna\s+understand|i\s+(?:just\s+)?wanna\s+know)")
QWORD = r"(?:can|could|do|does|did|is|are|will|would|what|why|how|where|when|which|who)"
BREAK = re.compile(r"(?<=[.?!;])\s+|\n+|\s+(?=" + LEADIN + r"\b)|\s+(?:and|but|so|because|since|also)\s+(?=" + QWORD + r"\b)|,\s+(?=" + QWORD + r"\b)", re.I)
LEAD = re.compile(r"^\s*" + LEADIN + r"\s*(?:(?:like|um|so|basically)\s+)*", re.I)
QUESTION = re.compile(r"\?|^\s*(?:" + QWORD + r"|whether)\b|^\s*tell me\b", re.I)


def pieces(message: str) -> list[str]:
    parts = [LEAD.sub("", p).strip(" ,.;") for p in BREAK.split(message) if p and p.strip(" ,.;")]
    return [p for p in parts if len(p.split()) >= MIN_PIECE]


def question_pieces(message: str) -> list[str]:
    """A piece is a question when it has a question mark or opens with a question word."""
    return [p for p in pieces(message) if QUESTION.search(p)]


def is_long(message: str) -> bool:
    return len(message.split()) >= LONG_WORDS
