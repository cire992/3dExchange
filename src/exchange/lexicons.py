"""Matching filename tokens against lexicons, and editing the user's lexicon files.

Words are tokenized like filenames, so "BaseColor" in a lexicon matches the tokens base|color, and
a word's plural forms (donuts, boxes, berries) match too. Edits go to the user's definitions folder
(``lexicons/<id>.toml``), which replaces the built-in lexicon of the same id.
"""

from __future__ import annotations

import fnmatch
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from exchange.definitions.schema import GENERATED_LEXICON_KINDS, DefinitionSet, Lexicon, LexiconTerm
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
        self._build_folder_names()

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

    # Whole folder names ---------------------------------------------------------------------

    def _build_folder_names(self) -> None:
        # Category folders: theme words, and category names (Props, Vehicles) but not every
        # category word: a product folder named Barrel or Sword is still a product.
        self._folder_forms: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        self._authors: dict[str, str] = {}
        for lex in self.lexicons.values():
            for term in lex.terms:
                if lex.kind == "author":
                    for name in (term.value, *term.words):
                        self._authors.setdefault(squash(name), term.value)
                    continue
                names = term.words if lex.kind == "theme" else (term.value,) if lex.kind == "category" else ()
                for name in names:
                    for form in word_forms(name) | {(squash(name),)}:
                        self._folder_forms[form[0]].append(form)
        for forms in self._folder_forms.values():
            forms.sort(key=len, reverse=True)

    def is_category_folder(self, name: str) -> bool:
        """Whether a folder's whole name is theme words and category names (Sci-Fi, Fantasy Props)."""
        tokens, i = tokenize(name), 0
        while i < len(tokens):
            form = next((f for f in self._folder_forms.get(tokens[i], ())
                         if tuple(tokens[i : i + len(f)]) == f), None)
            if form is None:
                return False
            i += len(form)
        return bool(tokens)

    def author(self, name: str) -> str | None:
        """The known author a folder's whole name is (any spelling: AeonSoul, Aeon Soul), or None."""
        return self._authors.get(squash(name))


def squash(text: str) -> str:
    """A name's tokens run together, so spellings of one name agree: "Aeon Soul" -> "aeonsoul"."""
    return "".join(tokenize(text)) or fold(text)


def with_generated(definitions: DefinitionSet, generated: Mapping[str, Iterable[tuple[str, str]]]) -> DefinitionSet:
    """``definitions`` with words the scanner found added to generated lexicons (authors).

    ``generated`` maps a lexicon id to (value, word) pairs. Spellings that squash alike join one
    term; the lexicon file's own terms come first and keep their values, and words the user
    removed (the file's ``exclude``) are never added back.
    """
    lexicons = dict(definitions.lexicons)
    for lexicon_id, pairs in generated.items():
        lexicon = lexicons.get(lexicon_id)
        if lexicon is None or lexicon.kind not in GENERATED_LEXICON_KINDS:
            continue
        excluded = {squash(w) for w in lexicon.exclude}
        terms = _editable(lexicon)
        by_key: dict[str, tuple[str, list[str], list[str]]] = {}
        for term in terms:
            for name in (term[0], *term[1]):
                by_key.setdefault(squash(name), term)
        for value, word in pairs:
            if squash(word) in excluded or squash(value) in excluded:
                continue
            term = by_key.get(squash(word)) or by_key.get(squash(value))
            if term is None:
                term = (value, [], [])
                terms.append(term)
                by_key[squash(value)] = term
            if squash(word) not in {squash(w) for w in term[1]}:
                term[1].append(word)
            by_key.setdefault(squash(word), term)
        lexicons[lexicon_id] = replace(lexicon, terms=tuple(
            LexiconTerm(value, tuple(words), tuple(patterns)) for value, words, patterns in terms))
    return replace(definitions, lexicons=lexicons)


# Editing ------------------------------------------------------------------------------------------


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_lexicon(lexicon_id: str, name: str, kind: str, terms: list[tuple[str, list[str], list[str]]],
                 exclude: Iterable[str] = ()) -> str:
    lines = ["# Edited by Exchange. This file replaces the built-in lexicon with the same id.", "",
             "[lexicon]", f"id = {_toml_string(lexicon_id)}", f"name = {_toml_string(name)}",
             f"kind = {_toml_string(kind)}", "format_version = 1"]
    if exclude:
        lines.append("exclude = [" + ", ".join(_toml_string(w) for w in exclude) + "]")
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
             user_dir: Path | None = None, excluded: bool | None = None) -> Path:
    """Add (or remove) a word under ``value`` in a lexicon, writing the user's copy of it.

    In a generated lexicon (authors) removing a word also excludes it, so scans never add it back,
    unless ``excluded`` is False; adding one un-excludes it. ``definitions`` must hold the
    lexicon files as loaded (not merged with generated words); they are updated in memory too,
    so the change applies without reloading.
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
    exclude = [w for w in lexicon.exclude if squash(w) != squash(word)]
    if lexicon.kind in GENERATED_LEXICON_KINDS and not present and excluded is not False:
        exclude.append(word)
    folder = (user_dir or user_definitions_dir()) / "lexicons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{lexicon_id}.toml"
    path.write_text(dump_lexicon(lexicon.id, lexicon.name, lexicon.kind, terms, exclude), encoding="utf-8")
    from exchange.definitions.loader import _read_toml, parse_lexicon

    definitions.lexicons[lexicon_id] = parse_lexicon(_read_toml(path), str(path))
    return path


def has_word(definitions: DefinitionSet, lexicon_id: str, value: str, word: str) -> bool:
    lexicon = definitions.lexicons.get(lexicon_id)
    return lexicon is not None and any(
        fold(t.value) == fold(value) and fold(word) in {fold(w) for w in t.words} for t in lexicon.terms)


def word_state(definitions: DefinitionSet, lexicon_id: str, value: str, word: str) -> bool | str | None:
    """True if the lexicon file has the word, "excluded" if the user removed a generated word."""
    if has_word(definitions, lexicon_id, value, word):
        return True
    lexicon = definitions.lexicons.get(lexicon_id)
    if lexicon is not None and squash(word) in {squash(w) for w in lexicon.exclude}:
        return "excluded"
    return None
