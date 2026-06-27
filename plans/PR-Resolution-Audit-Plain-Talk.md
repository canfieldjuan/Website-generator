# PR: Resolution Audit Plain Talk

## Why this slice exists

The Resolution Audit kit is now safer and richer, but the generated drafts can
still sound too polished, robotic, or corporate. The user wants to borrow from
Rudolf Flesch's plain-talk discipline and Yoast-style readability checks so
content sounds like a real operator explaining a real support problem.

This slice adds a Plain Talk layer: a style guide, a local readability checker,
and a prompt-contract rewrite pass. The goal is not to make every draft
childish. The goal is to make drafts clearer, more human, and easier to say out
loud while preserving the existing claims guard.

## Scope (this PR)

1. Add a `plain-talk.md` guide with target ranges, rewrite rules, before/after
   examples, and model instructions.
2. Add a standard-library `score_plain_talk.py` script that reports Flesch
   Reading Ease, Flesch-Kincaid grade, Flesch-style human interest, sentence
   length, complex words, reading time, SMOG, Coleman-Liau, Automated
   Readability Index, long sentences, and corporate/jargon hits.
3. Add a Plain Talk rewrite contract to `prompt-contracts.md`.
4. Update the README with the Plain Talk workflow and checker command.

### Files touched

- `plans/PR-Resolution-Audit-Plain-Talk.md`
- `content-pipeline/resolution-audit/plain-talk.md`
- `content-pipeline/resolution-audit/score_plain_talk.py`
- `content-pipeline/resolution-audit/prompt-contracts.md`
- `content-pipeline/resolution-audit/README.md`

## Mechanism

`plain-talk.md` adapts Flesch's reading-ease and human-interest ideas into
Resolution Audit drafting rules. The guide treats scores as signals, not as
absolute truth: sentence length and syllable count help catch dense writing,
while personal words and personal sentences help catch text that talks only
about systems instead of people.

`score_plain_talk.py` uses simple local heuristics so it can run anywhere:

- Flesch Reading Ease:
  `206.835 - 1.015 * average_sentence_length - 84.6 * average_syllables_per_word`
- Flesch-Kincaid grade:
  `0.39 * average_sentence_length + 11.8 * average_syllables_per_word - 15.59`
- Human interest:
  `3.635 * personal_words_per_100_words + 0.314 * personal_sentences_per_100_sentences`

The script also prints practical rewrite hints: long sentences, passive-ish
phrases, corporate nouns, likely jargon, complex words, and reading-ease labels.
It is an editorial check, not a formal test suite or SEO guarantee.

## Intentional

- No external dependencies. The checker uses only Python's standard library.
- No hard failing score gate. Plain Talk quality still needs human judgment.
- No change to the current prompt bundler. Operators can paste the Plain Talk
  guide manually while we see how useful it is.
- No claim that readability scores improve rankings or conversions.

## Deferred

- Add a bundler flag for `--include-plain-talk` if the rewrite pass becomes
  part of every Open WebUI session.
- Add fixture drafts and expected score ranges once real generated examples are
  saved.
- Add stricter CI-style score thresholds only after the operator has enough
  examples to tune them.

## Verification

- `python content-pipeline/resolution-audit/score_plain_talk.py --help`
- `printf 'Operational visibility enables cross-functional optimization of recurring support interactions.' >/tmp/plain-talk-corporate.txt`
- `python content-pipeline/resolution-audit/score_plain_talk.py /tmp/plain-talk-corporate.txt`
- `python content-pipeline/resolution-audit/score_plain_talk.py content-pipeline/resolution-audit/plain-talk.md --target blog`
- `python -m py_compile content-pipeline/resolution-audit/score_plain_talk.py`
- `git diff --check -- content-pipeline/resolution-audit/plain-talk.md content-pipeline/resolution-audit/score_plain_talk.py content-pipeline/resolution-audit/prompt-contracts.md content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Plain-Talk.md`
- `bash scripts/local_pr_review.sh --allow-dirty`

The strict clean-worktree local review cannot run until unrelated pre-existing
untracked workspace files are cleaned or stashed.

## Estimated Diff Size

Actual working diff size: 5 files, +956 / -20. This is over the 400 LOC soft
cap because the guide, checker, and prompt rewrite contract need to ship
together to make the workflow usable.
