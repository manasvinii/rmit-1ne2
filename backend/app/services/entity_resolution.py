"""Concept normalization and entity resolution.

Merges surface variants of the same concept:
  "Gradient Descent" / "gradient descent"      -> case + whitespace
  "Decision Trees" / "Decision Tree"           -> plural folding
  "Gradient decent" / "Gradient descent"       -> token-wise fuzzy match (typos)
  "Regularisation" / "Regularization"          -> fuzzy match (spelling variants)
  "Multi-Layer Perceptron (MLP)" / "MLP"       -> acronym aliasing
while keeping genuinely different concepts apart ("Linear Regression" vs "Logistic Regression").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, Optional

_ARTICLES = {"a", "an", "the"}
_KEEP_S = {"loss", "class", "bias", "analysis", "basis", "process", "less", "softmax", "lasso", "gauss", "bayes"}
_ACRONYM_DEF = re.compile(r"([A-Z][A-Za-z\-]+(?:[\s\-]+[A-Za-z][A-Za-z\-]+){0,5})\s*\(([A-Z][A-Za-z0-9]{1,7})s?\)")


def _singular(tok: str) -> str:
    if tok in _KEEP_S or len(tok) <= 3 or tok.endswith(("ss", "us", "is")):
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith(("sses", "xes", "ches", "shes")):
        return tok[:-2]
    if tok.endswith("s"):
        return tok[:-1]
    return tok


def normalize(name: str) -> str:
    """Canonical comparison key."""
    s = name.strip().lower()
    s = re.sub(r"\(.*?\)", " ", s)  # drop parenthetical acronyms/notes
    s = s.replace("&", " and ").replace("-", " ").replace("/", " ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    toks = [t for t in s.split() if t]
    while toks and toks[0] in _ARTICLES:
        toks = toks[1:]
    if not toks:
        return ""
    toks[-1] = _singular(toks[-1])
    return " ".join(toks)


def acronym_of(name: str) -> str:
    words = [w for w in re.split(r"[\s\-]+", re.sub(r"\(.*?\)", "", name)) if w and w.lower() not in _ARTICLES | {"of", "and", "for"}]
    return "".join(w[0] for w in words).upper()


def split_acronym(name: str) -> tuple[str, Optional[str]]:
    """'Multi-Layer Perceptron (MLP)' -> ('Multi-Layer Perceptron', 'MLP')"""
    m = re.match(r"^(.*?)\s*\(([A-Z][A-Za-z0-9]{1,7})s?\)\s*$", name.strip())
    if m and acronym_of(m.group(1)).startswith(m.group(2)[0]):
        return m.group(1).strip(), m.group(2)
    return name.strip(), None


def find_acronym_definitions(text: str) -> list[tuple[str, str]]:
    """Find 'Long Form Name (LFN)' definitions whose initials match the acronym."""
    out = []
    for m in _ACRONYM_DEF.finditer(text):
        long_form, acr = m.group(1).strip(), m.group(2)
        words = re.split(r"[\s\-]+", long_form)
        # take the trailing words whose initials spell the acronym
        for start in range(len(words)):
            cand = " ".join(words[start:])
            if acronym_of(cand) == acr.upper():
                out.append((cand, acr))
                break
    return out


def _token_similar(a: str, b: str) -> bool:
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return False
    for x, y in zip(ta, tb):
        if x == y:
            continue
        if min(len(x), len(y)) < 5 or SequenceMatcher(None, x, y).ratio() < 0.8:
            return False
    return True


def fuzzy_same(a: str, b: str, threshold: float = 0.9) -> bool:
    if a == b or (len(a) >= 6 and a.replace(" ", "") == b.replace(" ", "")):  # "hyper parameter" == "hyperparameter"
        return True
    if min(len(a), len(b)) < 6:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold and _token_similar(a, b)


@dataclass
class ConceptEntry:
    key: str  # canonical normalized key
    label: str  # display name (most frequent surface form)
    concept_type: str = "Concept"
    aliases: dict[str, str] = field(default_factory=dict)  # alias_norm -> surface form
    surface_counts: dict[str, int] = field(default_factory=dict)
    description: Optional[str] = None

    def add_surface(self, surface: str) -> None:
        self.surface_counts[surface] = self.surface_counts.get(surface, 0) + 1
        self.aliases.setdefault(normalize(surface), surface)
        # prefer the most frequent, then the longest-cased variant, as the label
        self.label = max(self.surface_counts, key=lambda s: (self.surface_counts[s], s[:1].isupper(), -len(s)))


class ConceptRegistry:
    """Resolves surface strings to canonical concepts within one course graph."""

    def __init__(self, seed_aliases: Optional[dict[str, str]] = None):
        self.entries: dict[str, ConceptEntry] = {}
        self._alias_index: dict[str, str] = {}  # alias_norm -> key
        self._seed = {normalize(k): v for k, v in (seed_aliases or {}).items()}

    def resolve(self, surface: str) -> Optional[str]:
        """Return the canonical key for a surface form, or None if unknown."""
        long_form, acr = split_acronym(surface)
        n = normalize(long_form)
        if not n:
            return None
        if n in self._alias_index:
            return self._alias_index[n]
        if acr and normalize(acr) in self._alias_index:
            return self._alias_index[normalize(acr)]
        if n in self._seed and normalize(self._seed[n]) in self._alias_index:
            return self._alias_index[normalize(self._seed[n])]
        for alias_norm, key in self._alias_index.items():
            if fuzzy_same(n, alias_norm):
                return key
        return None

    def add(self, surface: str, concept_type: str = "Concept", description: Optional[str] = None,
            aliases: Iterable[str] = ()) -> str:
        long_form, acr = split_acronym(surface)
        key = self.resolve(surface)
        if key is None:
            seed_target = self._seed.get(normalize(long_form))
            if seed_target:  # e.g. surface "GD" with seed GD -> gradient descent
                key = normalize(seed_target)
                if key not in self.entries:
                    self.entries[key] = ConceptEntry(key=key, label=seed_target, concept_type=concept_type)
                    self._index(key, seed_target)
            else:
                key = normalize(long_form)
                self.entries[key] = ConceptEntry(key=key, label=long_form, concept_type=concept_type)
        entry = self.entries[key]
        entry.add_surface(long_form)
        self._index(key, long_form)
        for a in [*aliases, *( [acr] if acr else [])]:
            if a and normalize(a):
                entry.aliases.setdefault(normalize(a), a)
                self._index(key, a)
        if description and not entry.description:
            entry.description = description
        if concept_type != "Concept" and entry.concept_type == "Concept":
            entry.concept_type = concept_type
        return key

    def add_alias(self, key: str, alias: str) -> None:
        if key in self.entries and normalize(alias):
            self.entries[key].aliases.setdefault(normalize(alias), alias)
            self._index(key, alias)

    def _index(self, key: str, surface: str) -> None:
        n = normalize(surface)
        if n and n not in self._alias_index:
            self._alias_index[n] = key

    def alias_items(self) -> Iterable[tuple[str, str]]:
        """(alias_norm, key)"""
        return self._alias_index.items()
