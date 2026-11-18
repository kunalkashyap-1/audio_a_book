"""Story intelligence without a language model.

Deliberately deterministic: quotative attribution plus recency fallback. It is not as good
as an LLM on hard cases, but it is free, instant, explainable, and it never invents a
character. The provider boundary in spec 04 lets an LLM replace this later without touching
call sites — see ``docs/specs/04-ai-providers.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SPEECH_VERBS = (
    "said|asked|replied|answered|cried|exclaimed|whispered|added|continued|observed|"
    "rejoined|returned|remarked|murmured|shouted|repeated|protested|suggested|"
    "declared|demanded|began|inquired|enquired|replied|retorted|interrupted|"
    "explained|admitted|agreed|insisted|urged|wondered|muttered|sighed|laughed"
)
QUOTE_RE = re.compile(r"[“\"]([^“”\"]{1,1200})[”\"]")
NAME_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,2})\b")
TAG_AFTER = re.compile(
    rf"(?:{SPEECH_VERBS})\s*,?\s*(?:(?:Mr|Mrs|Miss|Lady|Sir|Lord|Dr)\.?\s*)?"
    r"([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)",
    re.I,
)
TAG_BEFORE = re.compile(
    rf"([A-Z][a-z]{{2,}}(?:\s+[A-Z][a-z]{{2,}})?)\s+(?:{SPEECH_VERBS})\b",
)

STOPWORDS = {
    "the", "this", "that", "there", "then", "when", "what", "with", "but", "and", "for",
    "his", "her", "she", "he", "they", "them", "you", "not", "now", "chapter", "part",
    "book", "volume", "act", "scene", "mr", "mrs", "miss", "lady", "sir", "lord", "dr",
    "well", "yes", "no", "oh", "if", "as", "at", "in", "on", "of", "to", "it", "i",
    "my", "we", "our", "your", "their", "was", "were", "had", "have", "has", "will",
    "would", "could", "should", "must", "may", "might", "did", "does", "do", "be",
    "been", "being", "from", "into", "upon", "about", "after", "before", "again",
    "never", "always", "very", "only", "just", "too", "so", "such", "some", "any",
    "all", "one", "two", "first", "last", "next", "more", "most", "other", "another",
    "every", "each", "both", "few", "many", "much", "own", "same", "than", "too",
    "here", "where", "why", "how", "who", "which", "while", "because", "though",
    "although", "yet", "still", "even", "ever", "once", "twice", "nothing", "something",
    "anything", "everything", "nobody", "somebody", "anybody", "everybody",
}

ANGRY = {"angry", "furious", "indignant", "rage", "coldly", "bitterly", "harshly"}
FEARFUL = {"afraid", "fear", "terror", "trembling", "horror", "alarmed", "frightened"}
TENDER = {"gently", "softly", "tenderly", "kindly", "fondly", "smiled"}


@dataclass(frozen=True)
class Unit:
    kind: str                 # narration | dialogue | heading
    text: str
    speaker: str | None
    confidence: float
    method: str
    emotion: str = "neutral"
    intensity: int = 1
    pace: str = "normal"
    gap_after_ms: int = 120


@dataclass
class StoryCast:
    names: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------- cast

def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def extract_cast(text: str, limit: int = 14) -> StoryCast:
    counts: dict[str, int] = {}
    speech_hits: dict[str, int] = {}

    for match in NAME_RE.finditer(text):
        name = _clean_name(match.group(1))
        first = name.split()[0].lower()
        if first in STOPWORDS:
            continue
        counts[name] = counts.get(name, 0) + 1

    for pattern in (TAG_AFTER, TAG_BEFORE):
        for match in pattern.finditer(text):
            name = _clean_name(match.group(1))
            if name.split()[0].lower() in STOPWORDS:
                continue
            speech_hits[name] = speech_hits.get(name, 0) + 1
            counts.setdefault(name, 0)

    # Collapse "Elizabeth Harding" onto "Elizabeth", then drop a bare surname that only ever
    # appears inside a fuller name. Folding rather than dropping keeps a character who is
    # introduced once by full name above the mention threshold.
    multi = [name for name in counts if " " in name]
    first_tokens = {name.split()[0] for name in multi}
    last_tokens = {name.split()[-1] for name in multi}
    for other in multi:
        head = other.split()[0]
        counts[head] = counts.get(head, 0) + counts.pop(other, 0)
        speech_hits[head] = speech_hits.get(head, 0) + speech_hits.pop(other, 0)
    for name in list(counts):
        if name not in first_tokens and name in last_tokens and counts[name] < 3:
            counts.pop(name, None)
            speech_hits.pop(name, None)

    # A name is cast if it recurs, if it is ever attached to a speech tag, or if it was
    # introduced with a full name — a character may be named only once in a short story.
    scored = {
        name: counts[name] + 4 * speech_hits.get(name, 0)
        for name in counts
        if counts.get(name, 0) >= 2 or speech_hits.get(name, 0) >= 1
        or name in first_tokens
    }
    if not scored:
        return StoryCast()
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    cast = StoryCast()
    for i, (name, score) in enumerate(ranked):
        cast.names.append(name)
        cast.scores[name] = float(score)
        cast.roles[name] = "protagonist" if i == 0 else "character"
    return cast


# ---------------------------------------------------------------- blocks and units

def split_paragraphs(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in text.split("\n") if p.strip()]
    return parts


def _directive(text: str, kind: str) -> tuple[str, int, str]:
    lowered = text.lower()
    emotion, intensity, pace = "neutral", 1, "normal"
    if kind == "dialogue":
        if any(w in lowered for w in ANGRY):
            emotion, intensity = "tense", 2
        elif any(w in lowered for w in FEARFUL):
            emotion, intensity = "afraid", 2
        elif any(w in lowered for w in TENDER):
            emotion, intensity = "tender", 1
        if text.rstrip().endswith("!"):
            emotion, intensity = (emotion if emotion != "neutral" else "urgent"), \
                max(intensity, 2)
            pace = "fast"
        elif text.rstrip().endswith("?"):
            pace = "slow"
        if len(text) > 260:
            pace = "slow"
    return emotion, intensity, pace


def _resolve(candidate: str, known: list[str]) -> str | None:
    """Map "Darcy", "Colman" or "Mr. Darcy Colman" onto "Darcy Colman"."""
    if candidate in known:
        return candidate
    for name in known:
        if candidate.startswith(f"{name} ") or candidate.endswith(f" {name}"):
            return name
        if name.startswith(f"{candidate} ") or name.endswith(f" {candidate}"):
            return name
    return None


FEMININE = re.compile(r"\b(she|her|hers|herself|woman|lady|girl|mother|sister|wife|aunt|"
                      r"daughter|queen|princess)\b", re.I)
MASCULINE = re.compile(r"\b(he|him|his|himself|man|gentleman|boy|father|brother|husband|"
                       r"uncle|son|king|prince)\b", re.I)


def infer_genders(text: str, names: list[str]) -> dict[str, str]:
    """A weak prior from pronouns near each name. Never published as a fact.

    Used only to break ties when a tag says "she said" and two characters are in scope.
    ``?`` means "no evidence", and a ``?`` character is never chosen by gender alone.
    """
    out: dict[str, str] = {}
    for name in names:
        feminine = masculine = 0
        for match in re.finditer(rf"\b{re.escape(name)}\b", text):
            window = text[match.end():match.end() + 160]
            feminine += len(FEMININE.findall(window))
            masculine += len(MASCULINE.findall(window))
        if feminine > masculine:
            out[name] = "f"
        elif masculine > feminine:
            out[name] = "m"
        else:
            out[name] = "?"
    return out


class _Tracker:
    """Who was mentioned how recently, and who spoke last."""

    def __init__(self, known: list[str], genders: dict[str, str]) -> None:
        self.known = known
        self.genders = genders
        self.seen: dict[str, int] = {name: 0 for name in known}
        self.tick = 0
        self.last: str | None = None

    def note(self, text: str) -> None:
        for match in NAME_RE.finditer(text):
            name = _resolve(_clean_name(match.group(1)), self.known)
            if name:
                self.tick += 1
                self.seen[name] = self.tick

    def ranked(self) -> list[str]:
        return sorted((n for n in self.known if self.seen[n]),
                      key=lambda n: (-self.seen[n], n))

    def by_gender(self, gender: str | None) -> list[str]:
        ranked = self.ranked()
        if not gender:
            return ranked
        return [n for n in ranked if self.genders.get(n) == gender]


def _speaker_for_quote(paragraph: str, quote: str, tracker: _Tracker) -> tuple[
        str | None, float, str]:
    start = paragraph.find(quote)
    end = start + len(quote) if start >= 0 else len(paragraph)
    window = paragraph[max(0, start - 90):min(len(paragraph), end + 110)]

    # 1. An explicit attribution tag, preferring the one nearest the quote.
    best: tuple[int, str] | None = None
    for pattern in (TAG_BEFORE, TAG_AFTER):
        for match in pattern.finditer(window):
            name = _resolve(_clean_name(match.group(1)), tracker.known)
            if not name:
                continue
            distance = abs(match.start() - max(0, start - 90))
            if best is None or distance < best[0]:
                best = (distance, name)
    if best:
        return best[1], 0.92, "quotative"

    # 2. Exactly one character named in the paragraph.
    mentioned = [n for n in tracker.known if re.search(rf"\b{re.escape(n)}\b", paragraph)]
    if len(mentioned) == 1:
        return mentioned[0], 0.72, "single_mention"

    # 3. A gendered pronoun in the tag: "she said", "he replied", "said the old woman".
    gender = None
    if FEMININE.search(window) and not MASCULINE.search(window):
        gender = "f"
    elif MASCULINE.search(window) and not FEMININE.search(window):
        gender = "m"
    candidates = tracker.by_gender(gender) if gender else []
    if len(candidates) == 1:
        return candidates[0], 0.78, "pronoun"
    if candidates:
        return candidates[0], 0.62, "pronoun_ambiguous"

    # 4. Two-hander alternation: the last speaker is the least likely next speaker.
    ranked = tracker.ranked()
    if tracker.last and len(ranked) > 1:
        others = [n for n in ranked if n != tracker.last]
        if others:
            return others[0], 0.40, "alternation"

    # 5. Pure recency.
    if ranked:
        return ranked[0], 0.35, "recency"
    return None, 0.0, "unattributed"


def analyse_chapter(text: str, known: list[str],
                    genders: dict[str, str] | None = None) -> list[Unit]:
    units: list[Unit] = []
    tracker = _Tracker(known, genders or infer_genders(text, known))

    for paragraph in split_paragraphs(text):
        stripped = paragraph.strip()
        if not stripped:
            continue
        if len(stripped.split()) <= 6 and not stripped.endswith((".", "!", "?", "”", '"')):
            units.append(Unit(kind="heading", text=stripped, speaker="narrator",
                              confidence=1.0, method="heading", gap_after_ms=600))
            continue

        quote_spans = list(QUOTE_RE.finditer(paragraph))
        if not quote_spans:
            tracker.note(stripped)
            emotion, intensity, pace = _directive(stripped, "narration")
            units.append(Unit(
                kind="narration", text=stripped, speaker="narrator", confidence=1.0,
                method="narration", emotion=emotion, intensity=intensity, pace=pace,
            ))
            continue

        cursor = 0
        for match in quote_spans:
            before = paragraph[cursor:match.start()].strip()
            if before:
                tracker.note(before)
                emotion, intensity, pace = _directive(before, "narration")
                units.append(Unit(kind="narration", text=before, speaker="narrator",
                                  confidence=1.0, method="narration", emotion=emotion,
                                  intensity=intensity, pace=pace))
            quote = match.group(1).strip()
            speaker, confidence, method = _speaker_for_quote(paragraph, quote, tracker)
            if speaker:
                tracker.last = speaker
                tracker.tick += 1
                tracker.seen[speaker] = tracker.tick
            if quote:
                emotion, intensity, pace = _directive(quote, "dialogue")
                units.append(Unit(kind="dialogue", text=quote, speaker=speaker,
                                  confidence=confidence, method=method, emotion=emotion,
                                  intensity=intensity, pace=pace))
            cursor = match.end()

        tail = paragraph[cursor:].strip()
        if tail:
            tracker.note(tail)
            emotion, intensity, pace = _directive(tail, "narration")
            units.append(Unit(kind="narration", text=tail, speaker="narrator",
                              confidence=1.0, method="narration", emotion=emotion,
                              intensity=intensity, pace=pace))

    return [u for u in units if u.text.strip()]


def merge_short(units: list[Unit], min_chars: int = 40) -> list[Unit]:
    """Join tiny fragments onto the previous unit when the speaker matches.

    TTS quality collapses on three-word fragments; the cache is also more effective with
    fewer, longer calls.
    """
    out: list[Unit] = []
    for unit in units:
        if (out and len(unit.text) < min_chars and out[-1].speaker == unit.speaker
                and out[-1].kind == unit.kind):
            prev = out[-1]
            out[-1] = Unit(
                kind=prev.kind, text=f"{prev.text} {unit.text}".strip(),
                speaker=prev.speaker, confidence=min(prev.confidence, unit.confidence),
                method=prev.method, emotion=prev.emotion, intensity=prev.intensity,
                pace=prev.pace, gap_after_ms=unit.gap_after_ms,
            )
        else:
            out.append(unit)
    return out
