#!/usr/bin/env python3
"""Score Resolution Audit drafts for Plain Talk readability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


TARGETS = {
    "linkedin": {
        "reading_ease": (65, 80),
        "grade": (6, 9),
        "avg_sentence": (11, 18),
        "human_interest": 20,
        "reading_time_max": 2,
    },
    "reddit": {
        "reading_ease": (60, 78),
        "grade": (7, 10),
        "avg_sentence": (12, 20),
        "human_interest": 15,
        "reading_time_max": 2,
    },
    "reply": {
        "reading_ease": (70, 85),
        "grade": (5, 8),
        "avg_sentence": (8, 16),
        "human_interest": 25,
        "reading_time_max": 1,
    },
    "sales": {
        "reading_ease": (70, 85),
        "grade": (5, 8),
        "avg_sentence": (8, 16),
        "human_interest": 25,
        "reading_time_max": 1,
    },
    "blog": {
        "reading_ease": (60, 75),
        "grade": (7, 10),
        "avg_sentence": (12, 20),
        "human_interest": 15,
        "reading_time_max": 5,
    },
    "technical": {
        "reading_ease": (50, 70),
        "grade": (8, 12),
        "avg_sentence": (14, 22),
        "human_interest": 10,
        "reading_time_max": 6,
    },
}

PEOPLE_WORDS = {
    "i",
    "me",
    "my",
    "mine",
    "we",
    "us",
    "our",
    "ours",
    "you",
    "your",
    "yours",
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "they",
    "them",
    "their",
    "theirs",
    "customer",
    "customers",
    "agent",
    "agents",
    "founder",
    "founders",
    "operator",
    "operators",
    "lead",
    "leads",
    "team",
    "teams",
    "person",
    "people",
    "buyer",
    "buyers",
    "user",
    "users",
}

CORPORATE_PHRASES = [
    "actionable insights",
    "best-in-class",
    "cross-functional",
    "customer friction",
    "efficiency gains",
    "enable",
    "enables",
    "facilitate",
    "holistic",
    "leverage",
    "operational visibility",
    "operationalize",
    "optimize",
    "optimization",
    "robust",
    "scalable",
    "seamless",
    "strategic initiative",
    "streamline",
    "transformation",
    "unlock",
    "visibility",
    "workflow remediation",
]

PASSIVEISH_PATTERNS = [
    r"\b(is|are|was|were|be|being|been) (?:being )?\w+ed\b",
    r"\b(can|could|should|would|will|may|might|must) be \w+ed\b",
    r"\bhas been \w+ed\b",
    r"\bhave been \w+ed\b",
]

READING_EASE_LABELS = [
    (90, "Very Easy"),
    (80, "Easy"),
    (70, "Fairly Easy"),
    (60, "Standard"),
    (50, "Fairly Difficult"),
    (30, "Difficult"),
    (float("-inf"), "Very Difficult"),
]


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]*\]\([^)]+\)", " ", text)
    text = text.replace("**", "").replace("__", "")

    normalized = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("|") or re.fullmatch(r"[\-|: ]+", line):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line)
        if line and line[-1] not in ".!?":
            line = f"{line}."
        normalized.append(line)

    return " ".join(normalized)


def split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [piece.strip() for piece in pieces if re.search(r"[A-Za-z0-9]", piece)]
    return sentences or ([text.strip()] if text.strip() else [])


def words_in(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text.lower())


def count_syllables(word: str) -> int:
    word = word.lower()
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return 0

    exceptions = {
        "ai": 2,
        "queue": 1,
        "queued": 1,
        "pricing": 2,
        "flesch": 1,
        "yoast": 1,
        "seo": 3,
    }
    if word in exceptions:
        return exceptions[word]

    word = re.sub(r"e$", "", word)
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("le") and len(word) > 2 and word[-3] not in "aeiouy":
        count += 1
    return max(1, count)


def reading_ease_label(score: float) -> str:
    for floor, label in READING_EASE_LABELS:
        if score >= floor:
            return label
    return "Unknown"


def grade_label(grade: float) -> str:
    if grade <= 5:
        return "5th grade or below"
    if grade <= 6:
        return "6th grade"
    if grade <= 7:
        return "7th grade"
    if grade <= 9:
        return "8th-9th grade"
    if grade <= 12:
        return "10th-12th grade"
    if grade <= 16:
        return "College"
    if grade <= 18:
        return "College graduate"
    return "Professional/academic"


def score_text(raw_text: str, target: str) -> dict[str, Any]:
    text = strip_markdown(raw_text)
    sentences = split_sentences(text)
    words = words_in(text)
    word_count = len(words)
    sentence_count = len(sentences)
    syllable_count = sum(count_syllables(word) for word in words)
    character_count = sum(len(re.sub(r"[^A-Za-z0-9]", "", word)) for word in words)

    if not word_count or not sentence_count:
        raise ValueError("No scorable text found.")

    avg_sentence = word_count / sentence_count
    avg_syllables = syllable_count / word_count
    reading_ease = 206.835 - (1.015 * avg_sentence) - (84.6 * avg_syllables)
    grade = (0.39 * avg_sentence) + (11.8 * avg_syllables) - 15.59

    word_syllables = [(word, count_syllables(word)) for word in words]
    complex_word_items = [(word, syllables) for word, syllables in word_syllables if syllables >= 3]
    complex_word_count = len(complex_word_items)
    complex_word_frequency: dict[str, int] = {}
    for word, _syllables in complex_word_items:
        complex_word_frequency[word] = complex_word_frequency.get(word, 0) + 1
    top_complex_words = [
        {"word": word, "count": count}
        for word, count in sorted(
            complex_word_frequency.items(),
            key=lambda item: (-item[1], item[0]),
        )[:12]
    ]

    smog_index = 1.043 * ((complex_word_count * (30 / sentence_count)) ** 0.5) + 3.1291
    automated_readability_index = (
        (4.71 * (character_count / word_count))
        + (0.5 * avg_sentence)
        - 21.43
    )
    letters_per_100_words = character_count / word_count * 100
    sentences_per_100_words = sentence_count / word_count * 100
    coleman_liau_index = (
        (0.0588 * letters_per_100_words)
        - (0.296 * sentences_per_100_words)
        - 15.8
    )
    reading_time_minutes = max(1, round(word_count / 200))

    people_hits = [word for word in words if word in PEOPLE_WORDS]
    people_sentences = [
        sentence for sentence in sentences if any(word in PEOPLE_WORDS for word in words_in(sentence))
    ]
    people_words_per_100 = len(people_hits) / word_count * 100
    people_sentences_per_100 = len(people_sentences) / sentence_count * 100
    human_interest = (3.635 * people_words_per_100) + (0.314 * people_sentences_per_100)

    long_sentences = [
        {"words": len(words_in(sentence)), "sentence": sentence}
        for sentence in sentences
        if len(words_in(sentence)) > 22
    ]

    corporate_hits = sorted(
        {
            phrase
            for phrase in CORPORATE_PHRASES
            if re.search(rf"\b{re.escape(phrase)}\b", text, re.I)
        }
    )
    passiveish_hits = []
    for pattern in PASSIVEISH_PATTERNS:
        passiveish_hits.extend(match.group(0) for match in re.finditer(pattern, text, re.I))

    target_spec = TARGETS[target]
    hints = build_hints(
        reading_ease=reading_ease,
        grade=grade,
        avg_sentence=avg_sentence,
        human_interest=human_interest,
        complex_word_count=complex_word_count,
        reading_time_minutes=reading_time_minutes,
        long_sentences=long_sentences,
        corporate_hits=corporate_hits,
        passiveish_hits=passiveish_hits,
        target_spec=target_spec,
    )

    return {
        "target": target,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "syllable_count": syllable_count,
        "average_sentence_words": round(avg_sentence, 1),
        "average_syllables_per_word": round(avg_syllables, 2),
        "character_count": character_count,
        "complex_words": complex_word_count,
        "top_complex_words": top_complex_words,
        "reading_time_minutes": reading_time_minutes,
        "flesch_reading_ease": round(reading_ease, 1),
        "flesch_reading_ease_label": reading_ease_label(reading_ease),
        "flesch_kincaid_grade": round(grade, 1),
        "flesch_kincaid_grade_label": grade_label(grade),
        "smog_index": round(smog_index, 1),
        "coleman_liau_index": round(coleman_liau_index, 1),
        "automated_readability_index": round(automated_readability_index, 1),
        "human_interest": round(human_interest, 1),
        "people_words": len(people_hits),
        "people_sentences": len(people_sentences),
        "long_sentences": long_sentences[:8],
        "corporate_hits": corporate_hits,
        "passiveish_hits": passiveish_hits[:8],
        "hints": hints,
    }


def build_hints(
    *,
    reading_ease: float,
    grade: float,
    avg_sentence: float,
    human_interest: float,
    complex_word_count: int,
    reading_time_minutes: int,
    long_sentences: list[dict[str, Any]],
    corporate_hits: list[str],
    passiveish_hits: list[str],
    target_spec: dict[str, Any],
) -> list[str]:
    hints: list[str] = []

    ease_low, ease_high = target_spec["reading_ease"]
    grade_low, grade_high = target_spec["grade"]
    sentence_low, sentence_high = target_spec["avg_sentence"]
    human_floor = target_spec["human_interest"]
    reading_time_max = target_spec["reading_time_max"]

    if reading_ease < ease_low:
        hints.append("Reading ease is low. Shorten sentences and swap abstract words for plain ones.")
    elif reading_ease > ease_high:
        hints.append("Reading ease is very high. Check that the draft still has enough substance.")

    if reading_ease < 30:
        hints.append("Score is Very Difficult. Cut sentence length hard and replace jargon with common words.")
    elif reading_ease < 50:
        hints.append("Score is Difficult. Prefer common words and reduce 3+ syllable terms.")
    elif reading_ease < 60:
        hints.append("Score is Fairly Difficult. Replace complex words and break long sentences.")

    if grade > grade_high:
        hints.append("Grade level is high. Cut long words unless they are necessary.")
    elif grade < grade_low:
        hints.append("Grade level is low. Make sure the point still feels serious enough for the channel.")

    if avg_sentence > sentence_high:
        hints.append("Average sentence length is high. Split one idea per sentence.")
    elif avg_sentence < sentence_low:
        hints.append("Average sentence length is low. Vary rhythm if the draft feels choppy.")

    if human_interest < human_floor:
        hints.append("Human interest is low. Add true people words: you, we, customers, agents, support lead.")

    if complex_word_count:
        hints.append("Review the top complex words. Keep only the ones that carry real meaning.")

    if reading_time_minutes > reading_time_max:
        hints.append("Reading time is long for this format. Cut the setup or split the piece.")

    if long_sentences:
        hints.append("Break or trim the long sentences listed below.")

    if corporate_hits:
        hints.append("Replace corporate phrases with concrete people and actions.")

    if passiveish_hits:
        hints.append("Review passive-ish phrases. Name who does the action when you can.")

    return hints or ["Scores are in range. Do one out-loud read before posting."]


def print_report(score: dict[str, Any]) -> None:
    print("Plain Talk score")
    print(f"target: {score['target']}")
    print(f"words: {score['word_count']}")
    print(f"sentences: {score['sentence_count']}")
    print(f"avg sentence: {score['average_sentence_words']} words")
    print(f"Flesch Reading Ease: {score['flesch_reading_ease']}")
    print(f"reading ease label: {score['flesch_reading_ease_label']}")
    print(f"Flesch-Kincaid grade: {score['flesch_kincaid_grade']}")
    print(f"grade label: {score['flesch_kincaid_grade_label']}")
    print(f"SMOG index: {score['smog_index']}")
    print(f"Coleman-Liau index: {score['coleman_liau_index']}")
    print(f"Automated Readability Index: {score['automated_readability_index']}")
    print(f"Human interest: {score['human_interest']}")
    print(f"people words: {score['people_words']}")
    print(f"people sentences: {score['people_sentences']}")
    print(f"complex words: {score['complex_words']}")
    print(f"estimated reading time: {score['reading_time_minutes']} min")

    if score["top_complex_words"]:
        print("\nTop complex words:")
        for item in score["top_complex_words"]:
            print(f"- {item['word']} ({item['count']})")

    if score["corporate_hits"]:
        print("\nCorporate/jargon hits:")
        for phrase in score["corporate_hits"]:
            print(f"- {phrase}")

    if score["passiveish_hits"]:
        print("\nPassive-ish phrases:")
        for phrase in score["passiveish_hits"]:
            print(f"- {phrase}")

    if score["long_sentences"]:
        print("\nLong sentences:")
        for item in score["long_sentences"]:
            print(f"- {item['words']} words: {item['sentence']}")

    print("\nRewrite hints:")
    for hint in score["hints"]:
        print(f"- {hint}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score a draft for Plain Talk readability and human-interest signals.",
    )
    parser.add_argument("draft", type=Path, help="Markdown or text draft to score.")
    parser.add_argument(
        "--target",
        choices=sorted(TARGETS),
        default="linkedin",
        help="Format target used for rewrite hints.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        score = score_text(args.draft.read_text(encoding="utf-8"), args.target)
    except OSError as exc:
        print(f"score_plain_talk.py: could not read {args.draft}: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"score_plain_talk.py: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(score, indent=2))
    else:
        print_report(score)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
