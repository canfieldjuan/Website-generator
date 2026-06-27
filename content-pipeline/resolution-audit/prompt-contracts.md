# Resolution Audit Prompt Contracts

Use these in Open WebUI after pasting the current source files:

1. `source-pack.md`
2. `claims-guard.md`
3. `plain-talk.md` when the draft should sound more human
4. the relevant angle from `angles.md`
5. the Shared Context Block from this file
6. one channel contract from this file

Do not ask the model to ignore the guard. If a draft conflicts with the guard,
revise the draft or discard it.

## Shared Context Block

Paste this before any channel contract.

```text
You are helping draft content for The Resolution Audit.

Use only the product claims in the pasted source pack and claims guard. Treat
older notes, assumptions, and invented outcomes as unsafe.

The draft must:
- frame cost as estimated cost exposure, not guaranteed savings
- describe ownership as probable or investigatory when uncertain
- say drafted answers are review-ready, not auto-published
- say strong answers are backed by agent resolution or scoped resolution
  evidence when that evidence exists
- allow "no proven answer" when the ticket history lacks scoped resolution
  evidence
- treat product, policy, and process gaps as possible outcomes
- avoid raw customer data, names, emails, phone numbers, screenshots, or ticket
  excerpts
- use Plain Talk when `plain-talk.md` is pasted: short sentences, common words,
  concrete people and actions, and no corporate filler

The draft must not claim:
- guaranteed savings, guaranteed rankings, ticket-volume reduction, or fixed
  deflection percentages
- automatic help-center updates, live publishing, or automatic ticket answering
- certainty that a specific team owns an issue
- that the audit replaces support agents

Before drafting, restate the channel, audience, CTA posture, and the claim risk
you need to watch. If Plain Talk is in scope, also name the reading target and
the robotic language you need to avoid.
```

## Contract 1: LinkedIn POV Post

Use for founder, support lead, CX lead, or operator posts.

```text
Draft a LinkedIn POV post about The Resolution Audit.

Inputs:
- Audience: [founder / support lead / CX lead / operator]
- Angle: [ownership question / invisible repeat cost / build in public /
  pattern or finding / diagnostic not dashboard]
- Primary point: [one sentence]
- CTA posture: [ask for feedback / invite examples / offer Snapshot]
- Link or reply CTA: [none / upload link / "reply audit"]

Requirements:
- Open with a concrete support-queue observation, not a slogan.
- Explain the mechanism: repeated questions, ticket evidence, estimated cost
  exposure, and action routing.
- Include one sentence that admits what the audit does not promise.
- Keep the CTA low-pressure and honest.
- Use short paragraphs and no exclamation points.
- Avoid naming private customers or implying this is based on a specific
  customer's data.

Return:
1. One primary post, 120-220 words.
2. Three alternate hooks.
3. A Plain Talk pass: estimated reading ease target, phrases you simplified,
   and any long sentence you split.
4. A claim-risk checklist with pass/fail notes.
```

## Contract 2: Reddit-Style Discussion Post

Use for communities where direct promotion should be light or absent.

```text
Draft a Reddit-style discussion post about repeated support questions.

Inputs:
- Community context: [support / SaaS / founders / CX / operations]
- Angle: [ownership question / invisible repeat cost / diagnostic not dashboard]
- Promotion level: [none / transparent build-in-public / allowed offer]
- Question to ask the community: [one sentence]

Requirements:
- Lead with a genuine question or observation.
- Do not sound like a landing page.
- If mentioning The Resolution Audit, disclose that it is my tool.
- Do not ask for a CSV unless promotion is explicitly allowed.
- Invite disagreement and examples without asking for private ticket details.
- Keep the post useful even if the reader never clicks anything.

Return:
1. One discussion post, 100-180 words.
2. Two lower-pitch variants.
3. One comment I can leave if someone asks what I am building.
4. A Plain Talk pass: estimated reading ease target, phrases you simplified,
   and any long sentence you split.
5. A claim-risk checklist with pass/fail notes.
```

## Contract 3: Social Reply

Use when someone comments "audit," "curious," asks what the report does, or
shares a repeated support problem.

```text
Draft a reply to a social comment.

Inputs:
- Original comment: [paste comment]
- Relationship: [stranger / warm contact / customer / peer]
- Desired next step: [answer question / ask follow-up / offer Snapshot link]
- Public context I can safely mention: [category, help-center structure,
  visible support language, or none]

Requirements:
- Start by responding to the person, not pitching.
- If using public context, call it a hypothesis rather than an audit.
- Explain that the CSV is what turns a rough hypothesis into a real Snapshot.
- Do not imply we know their ticket volume, costs, or root causes without their
  export.
- Do not request raw private details in the public thread.
- Keep it concise enough to post as a reply.

Return:
1. One public reply under 120 words.
2. One warmer DM version under 160 words.
3. One safer no-link version.
4. A Plain Talk pass: phrases you simplified and any sentence that still sounds
   corporate.
5. A claim-risk checklist with pass/fail notes.
```

## Contract 4: Blog Outline

Use for long-form posts that explain the category, the diagnostic frame, or the
build-in-public story.

```text
Draft a blog outline for The Resolution Audit.

Inputs:
- Working title: [title]
- Audience: [founder / support lead / CX lead / operator]
- Thesis: [one sentence]
- Desired reader action: [understand problem / give feedback / try Snapshot]
- Claims to avoid: [optional]

Requirements:
- Structure the post around proof, mechanism, and practical action.
- Include a section that distinguishes documentation drafts from product,
  policy, and process gaps.
- Include a section that explains "no proven answer" without making the report
  sound like it failed.
- Include at least one disclaimer that the audit does not promise savings,
  guaranteed rankings, or ticket-volume reduction.
- Avoid keyword-stuffed SEO promises.
- Avoid pretending the audit performs live help-center publishing or ticket
  automation.

Return:
1. A title and subtitle.
2. A detailed outline with H2s and bullet points.
3. Three concrete examples or analogies that are safe to use.
4. A short intro draft under 180 words.
5. A Plain Talk pass for the intro: estimated reading ease target, phrases you
   simplified, and any long sentence you split.
6. A claim-risk checklist with pass/fail notes.
```

## Contract 5: Feedback Ask

Use when asking operators to react to the report shape, not to buy.

```text
Draft a feedback ask for The Resolution Audit.

Inputs:
- Feedback target: [report shape / Snapshot promise / pricing frame / gap
  language / upload flow]
- Audience: [support lead / founder / CX operator / product operator]
- What I am deciding: [one sentence]
- CTA: [comment / DM / review sample / upload CSV]

Requirements:
- Be transparent that this is my product.
- Ask for judgment on a specific decision, not generic feedback.
- Explain the current hypothesis in plain language.
- Make it easy to answer without sharing private data.
- Do not claim the product is proven by market results.
- If asking for uploads, frame the Snapshot as a bounded diagnostic, not a
  guaranteed sales or savings result.

Return:
1. One concise feedback post.
2. Three sharper versions of the actual question.
3. One follow-up reply for people who say "yes, send it."
4. A Plain Talk pass: phrases you simplified and any sentence that still sounds
   corporate.
5. A claim-risk checklist with pass/fail notes.
```

## Contract 6: Draft Self-Check

Run this before posting anything generated from the contracts.

```text
Audit the draft below against the pasted Resolution Audit source pack and
claims guard.

Draft:
[paste draft]

Return:
1. Verdict: Safe to post / Needs revision / Do not post.
2. Unsupported claims, with exact quoted phrases.
3. Missing qualifiers, especially around cost, ownership, evidence, privacy,
   and outcomes.
4. Any raw or identifying customer data that should be removed.
5. A revised version that keeps the idea but fixes the risks.

Be strict. A draft that implies guaranteed savings, fixed deflection,
auto-publishing, automatic ticket answering, or certain ownership should not
pass.
```

## Contract 7: Plain Talk Rewrite

Run this when a draft is safe but sounds robotic, polished, or corporate.

```text
Rewrite the draft below in Plain Talk.

Draft:
[paste draft]

Inputs:
- Format: [LinkedIn / Reddit / reply / sales DM / blog intro / technical]
- Target reader: [founder / support lead / CX lead / operator / product lead]
- Reading target: [default / easier / more technical]
- Words or phrases to preserve: [optional]

Requirements:
- Keep the source pack and claims guard intact.
- Do not add savings, ticket-reduction, ownership, privacy, or automation
  claims.
- Use short sentences and common words.
- Put people before systems when true.
- Replace corporate nouns with actions.
- Keep one idea per sentence.
- Preserve uncertainty language: may, appears, estimated, probable, when
  evidence exists.
- Make the draft sound like something a person could say out loud.

Return:
1. The rewritten draft.
2. A before/after list of up to five phrases you simplified.
3. Any sentence you split because it was too long.
4. Claim-risk notes for any qualifier you preserved.
5. A one-line score estimate: likely Flesch range, likely human-interest risk,
   and whether to run `score_plain_talk.py`.
```
