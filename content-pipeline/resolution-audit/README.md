# Resolution Audit Content Kit

This kit is the source pack for creating Resolution Audit content in Open
WebUI. It is not the website-redesign skill. It is a small operating kit for
drafting posts, replies, blog angles, and feedback asks that stay honest to the
current offer.

## Operator Flow

1. Pick the channel and job:
   - LinkedIn post
   - Reddit post
   - reply to a social comment
   - blog outline
   - feedback ask
2. Paste `source-pack.md`, `claims-guard.md`, and the relevant angle from
   `angles.md` into Open WebUI.
3. Generate the draft.
4. Check the draft against `claims-guard.md`.
5. Revise before posting if the draft promises savings, rankings, ticket-volume
   reductions, live publishing, or certainty about ownership.
6. Later slices will add prompt contracts and an ATLAS `verify_draft` handoff.

## Source Hierarchy

Use this order when two files disagree:

1. Current product code and landing copy in the portfolio repo.
2. `source-pack.md`.
3. `claims-guard.md`.
4. `angles.md`.
5. Older Desktop notes.

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

## What Comes Next

- Open WebUI system prompt and channel prompt contracts.
- A local bundler that assembles the right context for a channel.
- A structured handoff to the existing ATLAS `verify_draft` MCP verifier.
- Sanitized sample outputs and an outcomes log.
