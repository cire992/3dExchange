"""Matching filename tokens against lexicons, and editing the user's lexicon files.

Words are tokenized like filenames, so "BaseColor" in a lexicon matches the tokens base|color, and
a word's plural forms (donuts, boxes, berries) match too. Edits go to the user's definitions folder
(``lexicons/<id>.toml``), which replaces the built-in lexicon of the same id.
"""

from __future__ import annotations

import fnmatch
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from exchange.definitions.schema import DefinitionSet, Lexicon
from exchange.errors import DefinitionError
from exchange.paths import fold, user_definitions_dir
from exchange.scanner.tokenize import tokenize


@dataclass(frozen=True)
class Match:
    kind: str
    lexicon: str
    value: str
    word: str
    start: int  # token position
    length: int  # tokens covered


def word_forms(word: str) -> set[tuple[str, ...]]:
    """Token sequences a lexicon word matches: itself and plurals of its last token."""
    tokens = tuple(tokenize(word)) or (word.lower(),)
    forms = {tokens}
    last = tokens[-1]
    if len(last) > 2 and not last.isdigit():
        forms.add(tokens[:-1] + (last + "s",))
        forms.add(tokens[:-1] + (last + "es",))
        if last.endswith("y"):
            forms.add(tokens[:-1] + (last[:-1] + "ies",))
    return forms


class LexiconIndex:
    def __init__(self, definitions: DefinitionSet) -> None:
        self.lexicons = definitions.lexicons
        self._words: dict[str, list[tuple[tuple[str, ...], str, str, str, str]]] = defaultdict(list)
        self._patterns: list[tuple[str, str, str, str]] = []
        self.tag_names: dict[str, str] = {}
        for lex in definitions.lexicons.values():
            for term in lex.terms:
                if lex.kind == "category":
                    self.tag_names[fold(term.value)] = term.value
                for word in term.words:
                    for form in word_forms(word):
                        self._words[form[0]].append((form, lex.kind, lex.id, term.value, word))
                for pattern in term.patterns:
                    self._patterns.append((lex.kind, lex.id, term.value, pattern.lower()))
        for entries in self._words.values():
            entries.sort(key=lambda e: -len(e[0]))  # longest phrase first

    def match(self, tokens: list[str]) -> list[Match]:
        found, i = [], 0
        while i < len(tokens):
            for form, kind, lex_id, value, word in self._words.get(tokens[i], ()):
                if tuple(tokens[i : i + len(form)]) == form:
                    found.append(Match(kind, lex_id, value, word, i, len(form)))
                    # several lexicons may claim the same word; keep matching at this position
            longest = max((m.length for m in found if m.start == i), default=1)
            i += longest
        return found

    def match_stem(self, stem: str) -> list[Match]:
        stem = stem.lower()
        return [Match(kind, lex_id, value, pattern, 0, 0)
                for kind, lex_id, value, pattern in self._patterns if fnmatch.fnmatchcase(stem, pattern)]

    def is_index(self, token: str) -> bool:
        return token.isdigit() or any(kind == "index" for _, kind, *_ in self._words.get(token, ()))

    def clean(self, tokens: list[str]) -> list[str]:
        """Drop noise words (final, copy, v2 ...)."""
        drop: set[int] = set()
        for m in self.match(tokens):
            if m.kind == "ignore":
                drop.update(range(m.start, m.start + m.length))
        for i, token in enumerate(tokens):
            if token == "v" and i + 1 < len(tokens) and tokens[i + 1].isdigit():
                drop.update((i, i + 1))
        return [t for i, t in enumerate(tokens) if i not in drop]

    def known(self, token: str) -> bool:
        return token in self._words


# Editing ------------------------------------------------------------------------------------------


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_lexicon(lexicon_id: str, name: str, kind: str, terms: list[tuple[str, list[str], list[str]]]) -> str:
    lines = ["# Edited by Exchange. This file replaces the built-in lexicon with the same id.", "",
             "[lexicon]", f"id = {_toml_string(lexicon_id)}", f"name = {_toml_string(name)}",
             f"kind = {_toml_string(kind)}", "format_version = 1"]
    for value, words, patterns in terms:
        lines += ["", "[[term]]"]
        if value:
            lines.append(f"value = {_toml_string(value)}")
        if words:
            lines.append("words = [" + ", ".join(_toml_string(w) for w in words) + "]")
        if patterns:
            lines.append("patterns = [" + ", ".join(_toml_string(p) for p in patterns) + "]")
    return "\n".join(lines) + "\n"


def _editable(lexicon: Lexicon) -> list[tuple[str, list[str], list[str]]]:
    return [(t.value, list(t.words), list(t.patterns)) for t in lexicon.terms]


def set_word(definitions: DefinitionSet, lexicon_id: str, value: str, word: str, present: bool,
             user_dir: Path | None = None) -> Path:
    """Add (or remove) a word under ``value`` in a lexicon, writing the user's copy of it.

    The in-memory ``definitions`` are updated too, so the change applies without reloading.
    """
    lexicon = definitions.lexicons.get(lexicon_id)
    if lexicon is None:
        raise DefinitionError("lexicons", f"no lexicon {lexicon_id!r}")
    word = word.strip()
    if not word:
        raise DefinitionError(lexicon.source, "a lexicon word cannot be empty")
    terms = _editable(lexicon)
    target = next((t for t in terms if fold(t[0]) == fold(value)), None)
    if present:
        if target is None:
            target = (value, [], [])
            terms.append(target)
        if fold(word) not in {fold(w) for w in target[1]}:
            target[1].append(word)
    elif target is not None:
        target[1][:] = [w for w in target[1] if fold(w) != fold(word)]
        if not target[1] and not target[2]:
            terms.remove(target)
    folder = (user_dir or user_definitions_dir()) / "lexicons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{lexicon_id}.toml"
    path.write_text(dump_lexicon(lexicon.id, lexicon.name, lexicon.kind, terms), encoding="utf-8")
    from exchange.definitions.loader import _read_toml, parse_lexicon

    definitions.lexicons[lexicon_id] = parse_lexicon(_read_toml(path), str(path))
    return path


def has_word(definitions: DefinitionSet, lexicon_id: str, value: str, word: str) -> bool:
    lexicon = definitions.lexicons.get(lexicon_id)
    return lexicon is not None and any(
        fold(t.value) == fold(value) and fold(word) in {fold(w) for w in t.words} for t in lexicon.terms)
