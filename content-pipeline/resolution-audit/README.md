# Resolution Audit Content Kit

This kit is the source pack for creating Resolution Audit content in Open
WebUI. It is not the website-redesign skill. It is a small operating kit for
drafting posts, replies, blog angles, and feedback asks that stay honest to the
current offer.

Use `creative-manual.md` when the model needs more creative range than the
source pack and prompt contracts provide. It is especially useful for social
posts, Reddit analysis, blog framing, marketing copy, sales replies, and image
prompts. For smaller context-window models, paste the Compact Context Block
from `creative-manual.md` instead of the full manual.

Use `plain-talk.md` when a draft sounds robotic, polished, or corporate. It
adapts Flesch reading-ease and human-interest ideas into a Resolution Audit
rewrite pass. Use `score_plain_talk.py` on saved drafts to catch long
sentences, complex words, weak people-language, corporate phrases, and
readability-score warnings before posting.

Use `leak-index.md` when a draft needs a vendor-cost or billing-mechanic angle.
It is a router, not evidence by itself. Pick one leak tag, retrieve matching
rows from `evidence.jsonl`, then use the matching section in `frames.md` for
safe labels, unsafe language, and fallback wording. Treat exact vendor prices as
source-date snapshots: prefer the durable billing model in public copy and
re-check the live source page before publishing a specific dollar figure.
Run `validate_evidence.py` before using those cards when the source dates may be
stale.

## Operator Flow

1. Pick the CLI-backed channel and job:
   - LinkedIn post
   - Reddit post
   - reply to a social comment or sales note
   - blog outline
   - feedback ask
2. Build one pasteable prompt bundle:

   ```bash
   python content-pipeline/resolution-audit/bundle_prompt.py \
       --channel linkedin \
       --angle diagnostic-not-dashboard
   ```

3. Paste the bundle into Open WebUI and fill in the Inputs list inside the
   selected channel contract.
4. If the draft needs sharper creative direction, paste the Compact Context
   Block or relevant channel section from `creative-manual.md`.
5. If the draft uses a vendor-cost or leak angle, choose one tag from
   `leak-index.md`, validate the evidence file, and pass that tag to
   `bundle_prompt.py` with `--leak-tag`.

   ```bash
   python content-pipeline/resolution-audit/validate_evidence.py
   python content-pipeline/resolution-audit/bundle_prompt.py \
       --channel linkedin \
       --angle diagnostic-not-dashboard \
       --leak-tag repeat_resolution
   ```

6. Generate the draft.
7. If the draft sounds robotic, run Contract 7: Plain Talk Rewrite from
   `prompt-contracts.md`.
8. Run the final draft through the Contract 6 self-check in
   `prompt-contracts.md` after any Plain Talk rewrite.
9. Save the draft and score it locally:

   ```bash
   python content-pipeline/resolution-audit/score_plain_talk.py \
       /tmp/resolution-audit-draft.md \
       --target linkedin
   ```

10. Save the draft and prepare a verifier handoff packet:

   ```bash
   python content-pipeline/resolution-audit/prepare_verifier_packet.py \
       --draft /tmp/resolution-audit-draft.md \
       --channel linkedin \
       --output /tmp/resolution-audit-verify-packet.json
   ```

11. Revise before posting if the draft promises savings, guaranteed rankings,
   ticket-volume reductions, live publishing, or certainty about ownership.
12. Later infrastructure work can submit the packet to ATLAS `verify_draft`.

Manual-only creative and rewrite jobs:

- image prompts
- marketing copy that does not fit a blog, LinkedIn, Reddit, feedback, or reply
  contract
- Plain Talk rewrites that start from an existing draft instead of a new
  channel prompt

For these, use the Manual fallback below. They are not `bundle_prompt.py`
channels yet.

Manual fallback:

1. Paste `source-pack.md`, `claims-guard.md`, and the relevant angle from
   `angles.md` into Open WebUI.
2. Paste either the Compact Context Block from `creative-manual.md` or the
   relevant channel section when the draft needs sharper creative direction.
3. Paste the matching `leak-index.md`, `evidence.jsonl`, and `frames.md` slices
   when the draft uses a vendor-cost or leak angle.
4. Paste `plain-talk.md` when the draft should sound more direct and human.
5. Paste the Shared Context Block from `prompt-contracts.md`.
6. Paste the matching channel contract from `prompt-contracts.md`.
7. Generate the draft.
8. Run the Plain Talk rewrite contract if the draft still sounds corporate.
9. Run the final draft through the self-check contract in
   `prompt-contracts.md` after any Plain Talk rewrite.
10. Revise before posting if the draft promises savings, guaranteed rankings,
   ticket-volume reductions, live publishing, or certainty about ownership.

## Source Hierarchy

Use this order when two files disagree:

1. Current product code and landing copy in the portfolio repo.
2. `source-pack.md`.
3. `claims-guard.md`.
4. `creative-manual.md` for creative range, examples, and channel patterns.
5. `plain-talk.md` for voice and readability.
6. `leak-index.md`, `evidence.jsonl`, and `frames.md` for vendor-cost leak
   routing.
7. `angles.md`.
8. Older Desktop notes.

Older notes are treated as raw material, not source of truth. If an older note
claims a fixed deflection percentage, live self-service-center launch, automatic
help-center updates, or guaranteed savings, do not use that claim.

## What This Slice Does

- Preserves the strong "audit the repeated questions and route the root cause"
  positioning.
- Preserves the useful social angles from the loose Resolution Audit content
  kit.
- Preserves the reply-flow idea: give useful public context before asking for a
  ticket export.
- Removes unsupported copy that made the offer sound like a live deflection
  platform.
- Adds a creative manual for richer content primitives, channel patterns, and
  image prompt direction.
- Adds a Plain Talk guide and readability checker for less robotic drafts.
- Adds a leak router, evidence cards, and safe framing for vendor-cost angles.
- Adds paste-ready prompt contracts for the common Open WebUI drafting jobs.
- Adds a local prompt bundler for one-command copy/paste context assembly.
- Adds a local verifier handoff packet for the ATLAS `verify_draft` shape.

## What Comes Next

- Sanitized sample outputs and an outcomes log.
