from __future__ import annotations

from aab_story import (Unit, analyse_chapter, extract_cast, infer_genders, merge_short,
                       split_paragraphs)
from aab_tts import sentences, speakable, split_for_tts

CHAPTER = """The cottage at the end of the lane belonged to Elizabeth Harding, and she had
lived there for eleven years.

"I will not sell it," she said.

Mr. Darcy Colman, who had come from the city with a folder of papers, looked up from the
table. "The offer is generous," he replied.

"It is not generous," Elizabeth said. "It is merely large."
"""


def test_cast_prefers_people_who_speak() -> None:
    cast = extract_cast(CHAPTER)
    assert "Elizabeth" in cast.names
    assert "Darcy" in cast.names
    assert "The" not in cast.names
    assert cast.names[0] in {"Darcy", "Elizabeth"}


def test_cast_folds_full_names() -> None:
    cast = extract_cast(CHAPTER)
    assert "Elizabeth Harding" not in cast.names
    assert "Darcy Colman" not in cast.names


def test_gender_prior_is_evidence_based() -> None:
    cast = extract_cast(CHAPTER)
    genders = infer_genders(CHAPTER, cast.names)
    assert genders["Elizabeth"] == "f"
    assert genders["Darcy"] == "m"


def test_pronoun_attribution() -> None:
    cast = extract_cast(CHAPTER)
    units = analyse_chapter(CHAPTER, cast.names, infer_genders(CHAPTER, cast.names))
    first_dialogue = next(u for u in units if u.kind == "dialogue")
    assert first_dialogue.speaker == "Elizabeth"
    assert first_dialogue.method == "pronoun"


def test_quotative_attribution() -> None:
    cast = extract_cast(CHAPTER)
    units = analyse_chapter(CHAPTER, cast.names, infer_genders(CHAPTER, cast.names))
    by_text = {u.text: u for u in units}
    assert by_text["It is not generous,"].speaker == "Elizabeth"
    assert by_text["It is not generous,"].method == "quotative"
    assert by_text["It is merely large."].speaker == "Elizabeth"


def test_single_mention_resolves_speaker() -> None:
    cast = extract_cast(CHAPTER)
    units = analyse_chapter(CHAPTER, cast.names, infer_genders(CHAPTER, cast.names))
    offer = next(u for u in units if u.text.startswith("The offer is generous"))
    assert offer.speaker == "Darcy"


def test_no_character_is_invented() -> None:
    cast = extract_cast(CHAPTER)
    units = analyse_chapter(CHAPTER, cast.names, infer_genders(CHAPTER, cast.names))
    speakers = {u.speaker for u in units if u.kind == "dialogue"}
    assert None not in speakers
    assert speakers <= set(cast.names)


def test_alternation_without_attribution() -> None:
    text = (
        "Elizabeth put down the cup. Darcy watched her from the doorway.\n\n"
        '"You came back," he said.\n\n'
        '"I did."\n\n'
        '"Why?"\n\n'
        '"You know why."\n'
    )
    units = analyse_chapter(text, ["Elizabeth", "Darcy"], {"Elizabeth": "f", "Darcy": "m"})
    dialogue = [u.speaker for u in units if u.kind == "dialogue"]
    assert len(dialogue) == 4
    assert dialogue[0] != dialogue[1]
    assert dialogue[1] != dialogue[2]


def test_headings_become_heading_units() -> None:
    units = analyse_chapter("Chapter One\n\n" + "Some actual prose that is long enough to be "
                            "read aloud without sounding like a fragment at all.", [])
    assert units[0].kind == "heading"
    assert units[0].gap_after_ms == 600


def test_directives_follow_punctuation() -> None:
    units = analyse_chapter('"Get out!" he shouted.\n\n"Why?" she asked.\n',
                            ["Elizabeth", "Darcy"], {"Elizabeth": "f", "Darcy": "m"})
    shouts = [u for u in units if u.kind == "dialogue"]
    assert shouts[0].pace == "fast"
    assert shouts[0].intensity >= 2
    assert shouts[1].pace == "slow"


def test_merge_short_joins_fragments() -> None:
    units = [
        Unit(kind="narration", text="A long enough opening sentence that stands by itself.",
             speaker="narrator", confidence=1.0, method="narration"),
        Unit(kind="narration", text="And then.", speaker="narrator", confidence=1.0,
             method="narration"),
        Unit(kind="narration", text="A different speaker line that should not be joined.",
             speaker="someone-else", confidence=1.0, method="narration"),
    ]
    merged = merge_short(units)
    assert len(merged) == 2
    assert merged[0].text.endswith("And then.")


def test_paragraph_splitting() -> None:
    assert split_paragraphs("one\n\n two \n\nthree") == ["one", "two", "three"]
    assert split_paragraphs("one\ntwo\nthree") == ["one", "two", "three"]


def test_speakable_expands_abbreviations() -> None:
    assert speakable("Mr. Darcy met Mrs. Bennet.") == "Mister Darcy met Missus Bennet."
    assert speakable("well—then") == "well, then"


def test_sentence_splitting_keeps_abbreviations() -> None:
    parts = sentences("Mr. Darcy arrived. He sat down.")
    assert parts == ["Mr. Darcy arrived.", "He sat down."]


def test_split_for_tts_respects_budget() -> None:
    text = " ".join(["This sentence is reasonably long and should be packed carefully."] * 12)
    chunks = split_for_tts(text, max_chars=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_for_tts_never_drops_text() -> None:
    text = "x" * 900
    chunks = split_for_tts(text, max_chars=100)
    assert "".join(chunks) == text
