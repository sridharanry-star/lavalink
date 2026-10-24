from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Tuple

TAMIL_BLOCK = (0x0B80, 0x0BFF)

_TAMIL_VOWELS = {
    "அ": "a", "ஆ": "aa", "இ": "i", "ஈ": "ii", "உ": "u",
    "ஊ": "uu", "எ": "e", "ஏ": "ee", "ஐ": "ai", "ஒ": "o",
    "ஓ": "oo", "ஔ": "au", "ஃ": "h",
}
_TAMIL_SIGNS = {
    "ா": "aa", "ி": "i", "ீ": "ii", "ு": "u", "ூ": "uu",
    "ெ": "e", "ே": "ee", "ை": "ai", "ொ": "o", "ோ": "oo",
    "ௌ": "au",
}
_TAMIL_CONSONANTS = {
    "க": "k", "ங": "ng", "ச": "s", "ஞ": "ny", "ட": "t",
    "ண": "n", "த": "th", "ந": "n", "ப": "p", "ம": "m",
    "ய": "y", "ர": "r", "ல": "l", "வ": "v", "ழ": "zh",
    "ள": "l", "ற": "r", "ன": "n", "ஜ": "j", "ஷ": "sh",
    "ஸ": "s", "ஹ": "h", "க்ஷ": "ksh",
}


def contains_tamil_script(text: str) -> bool:
    return any(TAMIL_BLOCK[0] <= ord(char) <= TAMIL_BLOCK[1] for char in str(text or ""))


def normalize_search_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def tamil_script_to_latin(text: str) -> str:
    """Convert common Tamil orthography into a plain Latin search form."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    output = []
    index = 0
    while index < len(value):
        char = value[index]
        if value.startswith("க்ஷ", index):
            output.append("ksh")
            index += 3
            continue
        if char in _TAMIL_CONSONANTS:
            syllable = _TAMIL_CONSONANTS[char]
            following = value[index + 1] if index + 1 < len(value) else ""
            if following == "்":
                output.append(syllable)
                index += 2
                continue
            if following in _TAMIL_SIGNS:
                output.append(syllable + _TAMIL_SIGNS[following])
                index += 2
                continue
            output.append(syllable + "a")
        elif char in _TAMIL_VOWELS:
            output.append(_TAMIL_VOWELS[char])
        elif char == "்":
            pass
        elif char in ("\u200c", "\u200d"):
            pass
        else:
            output.append(char)
        index += 1
    return normalize_search_text("".join(output))


def phonetic_normalize(text: str) -> str:
    """Fold common Tamil/Tanglish vowel-length and consonant spelling variants."""
    value = normalize_search_text(text)
    value = re.sub(r"aai", "ai", value)
    for source, target in (("ae", "e"), ("aa", "a"), ("ee", "i"),
                           ("ii", "i"), ("oo", "u"), ("uu", "u"),
                           ("dh", "th"), ("bh", "b"), ("ph", "p"),
                           ("zh", "l"), ("ch", "s"), ("c", "s")):
        value = value.replace(source, target)
    for source, target in (("thth", "th"), ("ngng", "ng"), ("ny ny", "ny"),
                           ("kk", "k"), ("pp", "p"), ("tt", "t"),
                           ("nn", "n"), ("ll", "l"), ("rr", "r")):
        value = value.replace(source, target)
    value = re.sub(r"\b(y|ya)(e|a)", "e", value)
    return " ".join(value.split())


@lru_cache(maxsize=1)
def _tamil_hints() -> tuple[str, ...]:
    try:
        from .constants import LANGUAGES
        raw_hints = LANGUAGES.get("tamil", {}).get("keywords", ())
    except Exception:
        raw_hints = ("tamil", "tamizh", "thamizh", "kollywood", "tanglish", "kuthu", "anbe", "nenje")
    return tuple(normalize_search_text(hint) for hint in raw_hints if hint)


def matching_forms(text: str, tamil_aware: bool | None = None) -> Tuple[str, ...]:
    raw = normalize_search_text(text)
    roman = tamil_script_to_latin(text) if contains_tamil_script(text) else raw
    if tamil_aware is None:
        tamil_aware = contains_tamil_script(text) or is_tamil_context(text)
    forms = (raw, roman, phonetic_normalize(roman)) if tamil_aware else (raw, roman)
    return tuple(dict.fromkeys(form for form in forms if form))


def query_family_key(text: str) -> str:
    """Normalize Tamil-script/Tanglish query variants for leak-resistant evaluation splits."""
    value = normalize_search_text(text)
    value = re.sub(r"^(?:play|please|listen|p)\s+", "", value)
    value = re.sub(r"\b(?:tamil|tamizh|thamizh|song|songs|music|audio|official|video|lyrics?)\b", " ", value)
    value = " ".join(value.split())
    forms = matching_forms(value, tamil_aware=True)
    return forms[-1] if forms else value


def token_recall(left: str, right: str, ignored: Iterable[str] = ()) -> float:
    """Return the strongest token recall across native, romanized, and phonetic forms."""
    ignored_tokens = set(ignored)
    tamil_aware = is_tamil_context(left) or is_tamil_context(right)
    best = 0.0
    for left_form in matching_forms(left, tamil_aware=tamil_aware):
        left_tokens = {token for token in left_form.split() if len(token) > 1 and token not in ignored_tokens}
        if not left_tokens:
            continue
        for right_form in matching_forms(right, tamil_aware=tamil_aware):
            right_tokens = {token for token in right_form.split() if len(token) > 1}
            best = max(best, len(left_tokens & right_tokens) / len(left_tokens))
    return best


def best_similarity(left: str, right: str, tamil_aware: bool | None = None) -> float:
    from difflib import SequenceMatcher

    if tamil_aware is None:
        tamil_aware = is_tamil_context(left) or is_tamil_context(right)
    return max(
        (SequenceMatcher(None, a, b).ratio()
         for a in matching_forms(left, tamil_aware=tamil_aware)
         for b in matching_forms(right, tamil_aware=tamil_aware)),
        default=0.0,
    )


def is_tamil_context(query: str, candidates: Iterable[dict] = ()) -> bool:
    """Identify Tamil searches from script, common Tanglish terms, and catalog metadata."""
    if contains_tamil_script(query):
        return True
    def has_hint(value: str) -> bool:
        normalized = f" {normalize_search_text(value)} "
        return any(f" {hint} " in normalized for hint in _tamil_hints() if hint)

    if has_hint(query):
        return True
    for candidate in candidates or ():
        text = " ".join(str(candidate.get(key) or "") for key in ("title", "song_name", "artist", "artists", "uploader", "album"))
        if contains_tamil_script(text) or has_hint(text):
            return True
    return False
