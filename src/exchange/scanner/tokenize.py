"""Filename tokenizer: ``Donut01_Pink`` -> ``donut | 01 | pink``.

Splits on separators (underscores, spaces, hyphens, dots, brackets), camelCase and digit
boundaries. Lexicon matching on these tokens comes in Roadmap phase 3.
"""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[\s_\-.,+&'()\[\]{}]+")
_PARTS = re.compile(
    r"[A-Z]+(?=[A-Z][a-z])"  # acronym before a capitalized word: HD|Texture
    r"|[A-Z]?[a-z]+"  # Word or word
    r"|[A-Z]+"  # ACRONYM
    r"|\d+"  # 01
    r"|[^\W\d_]+"  # other letters (accented, non-Latin)
)


def tokenize(name: str) -> list[str]:
    tokens: list[str] = []
    for chunk in _SEPARATORS.split(name):
        tokens.extend(m.group(0).lower() for m in _PARTS.finditer(chunk))
    return tokens
