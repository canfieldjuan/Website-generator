# Resolution Audit Source Pack

Use this as the stable product context for Open WebUI drafts.

## Product Name

The public frame is "The Resolution Audit." The free first step is a Snapshot
or Resolution Snapshot. The paid expansion is the full Resolution Audit.

Avoid older names unless writing about the history of the product.

## What It Does

The Resolution Audit reads a support-ticket CSV and turns repeated questions
into an evidence-backed action queue.

The current product story:

- Upload a support-ticket export, typically from Zendesk or Freshdesk.
- The system groups repeated questions from closed ticket history.
- The Snapshot shows the top repeat question, estimated cost exposure, and one
  answer backed by agent resolution evidence when that evidence exists.
- The Snapshot also surfaces at least one high-cost unresolved gap when the
  tickets do not contain a proven answer.
- The full audit expands that pattern across the ranked backlog.
- The report separates ready-to-review documentation drafts from product,
  policy, or process gaps.

## Mechanism To Emphasize

This is the proof language to reuse:

- Each finding traces to repeat-ticket volume, resolution evidence, estimated
  cost exposure, and source tickets.
- Drafted resolutions are anchored to source ticket IDs.
- If the ticket history does not contain scoped resolution evidence, the issue
  is marked as "no proven answer" rather than invented.
- The report is a diagnostic, not a dashboard. It tells the operator what to
  review, publish, route, or investigate next.

## Buyer And Reader

Write for a founder, support lead, CX lead, operator, or small-team owner who is
close enough to the inbox to know repeated questions are real.

They do not need enterprise theater. They need:

- the repeat issue named clearly
- the cost exposure made visible
- the next owner or action made practical
- the risk controls stated plainly

## Current Offer Shape

The Snapshot is a gate for the customer's sake. It should help them decide
whether a full audit is worth the investment before they commit.

The useful framing:

- If the ticket history has enough repeated unresolved questions, the full
  audit may be worth reviewing.
- If the signal is thin, the Snapshot should still give a bounded starting
  point instead of a sales pitch.
- The full report should provide a ranked, source-backed queue of questions,
  answers, and operational blind spots.

## Voice

Plain-spoken diagnostic direct response.

Use:

- short sentences
- concrete nouns
- mechanisms instead of hype
- "because" when a claim needs logic
- direct acknowledgment of what the audit does not do

Avoid:

- exclamation points
- fake urgency
- "AI magic" language
- overconfident outcome claims
- claims that every repeated ticket is fixable with documentation

## Good Core Lines

Use or adapt these:

- "If customers keep asking the same question, that means the answer is not
  where customers are looking."
- "Instead of guessing, we audit."
- "The fix may already be sitting in your old tickets."
- "The expensive repeat is not always a support problem. Sometimes it is a
  product, policy, or process problem showing up in the support queue."
- "The report separates ready-to-review documentation drafts from the gaps a
  help article cannot solve."

## Data And Privacy Posture

Safe public posture:

- We do not need PII to find repeated questions.
- Browser and backend controls reduce supported PII exposure before report
  output.
- Do not include customer names, raw ticket text, emails, phone numbers, or
  screenshots in public examples.
- Public examples should be anonymized and aggregate.

Do not invent a stronger privacy, retention, compliance, or security claim than
the current product copy supports.
