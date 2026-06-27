# Plain Talk Guide

Use this guide to rewrite Resolution Audit content so it sounds like a person
talking to another person.

The aim is plain force, not bland simplicity. A good draft should feel clear
enough to say out loud and sharp enough that a support lead would forward it.

## Source Idea

Rudolf Flesch's plain-talk work treats readability as a mix of two things:

- **Reading ease:** shorter sentences and simpler words are easier to read.
- **Human interest:** writing feels more alive when it uses people words and
  people sentences.

Yoast SEO uses the Flesch Reading Ease score as one readability signal. For
this kit, treat the scores as editorial warning lights, not as truth. A draft
can score well and still be dull. A draft can use a hard word and still be
right. The point is to catch the robotic patterns early.

## Target Ranges

Use these as defaults:

| Format | Flesch Reading Ease | Grade Level | Avg Sentence | Human Interest |
|---|---:|---:|---:|---:|
| LinkedIn post | 65-80 | 6-9 | 11-18 words | 20+ |
| Reddit analysis | 60-78 | 7-10 | 12-20 words | 15+ |
| Social reply | 70-85 | 5-8 | 8-16 words | 25+ |
| Sales or DM copy | 70-85 | 5-8 | 8-16 words | 25+ |
| Blog intro | 60-75 | 7-10 | 12-20 words | 15+ |
| Technical explanation | 50-70 | 8-12 | 14-22 words | 10+ |

Do not chase the number at the cost of accuracy. The claims guard still wins.

## Score Labels

The local checker labels Flesch Reading Ease like this:

| Score | Label |
|---:|---|
| 90+ | Very Easy |
| 80-89 | Easy |
| 70-79 | Fairly Easy |
| 60-69 | Standard |
| 50-59 | Fairly Difficult |
| 30-49 | Difficult |
| under 30 | Very Difficult |

For most public Resolution Audit content, "Fairly Easy" or "Standard" is the
right neighborhood. "Very Easy" can work for replies and DMs. "Difficult" is a
warning unless the piece is intentionally technical.

## Extra Metrics

`score_plain_talk.py` also reports:

- **Complex words:** words with three or more syllables. These are not always
  bad, but too many make a draft feel slow.
- **Top complex words:** the repeated hard words to review first.
- **SMOG Index:** another grade-level signal based on complex words.
- **Coleman-Liau Index:** a grade-level signal based on characters, words, and
  sentences.
- **Automated Readability Index:** a grade-level signal based on characters per
  word and words per sentence.
- **Estimated reading time:** rough reading time at 200 words per minute.

Use the extra formulas as a second opinion. If all of them say the draft is
hard, it probably is. If only one complains, read the draft out loud and decide.

## The Plain Talk Pass

After a model drafts content, run this pass:

1. Cut the throat-clearing.
2. Break long sentences.
3. Replace abstract nouns with people and actions.
4. Keep one idea per sentence.
5. Put the person before the system.
6. Add "you," "we," "customers," "agents," or "support team" where true.
7. Replace corporate rhythm with spoken rhythm.
8. Keep the claim qualifiers: may, appears, estimated, probable, when evidence
   exists.

## What To Cut

These words are not banned, but they are warning lights:

- leverage
- optimize
- operationalize
- enable
- unlock
- streamline
- robust
- scalable
- comprehensive
- actionable insights
- cross-functional alignment
- visibility
- transformation
- efficiency gains
- strategic initiative
- holistic
- seamless
- best-in-class

Plain replacements:

| Corporate | Plain Talk |
|---|---|
| "operational visibility" | "what the team can see" |
| "cross-functional ownership" | "who needs to fix it" |
| "recurring support interactions" | "the same question coming back" |
| "knowledge optimization" | "making the answer easier to find" |
| "workflow remediation" | "fixing the broken step" |
| "customer self-service enablement" | "helping customers answer it without waiting" |
| "AI-powered insights" | "the report points to the repeat" |

## Before And After

### Example 1

Before:

```text
The Resolution Audit enables teams to identify recurring support interactions
and operationalize cross-functional remediation workflows.
```

After:

```text
The Resolution Audit shows which questions keep coming back and who may need
to fix the cause.
```

Why it works:

- "shows" beats "enables"
- "questions keep coming back" beats "recurring support interactions"
- "who may need to fix the cause" keeps the ownership claim qualified

### Example 2

Before:

```text
AI deflection metrics can create visibility gaps around unresolved customer
friction.
```

After:

```text
The bot may close the chat. That does not prove the customer got unstuck.
```

Why it works:

- It names the actor: the bot.
- It names the person: the customer.
- It turns a vague gap into a testable claim.

### Example 3

Before:

```text
The report surfaces documentation opportunities and process optimization
candidates.
```

After:

```text
Some repeats can become help-center drafts. Others need a product, billing, or
policy owner to look at the cause.
```

Why it works:

- It separates the two outcomes.
- It avoids pretending every repeat is a content problem.
- It uses the current claim guard.

## Sentence Rules

Most sentences should be under 18 words.

Use a long sentence only when it earns its keep. If a sentence has more than
25 words, try splitting it.

Weak:

```text
When support teams evaluate repeated customer questions through traditional
analytics dashboards, they often miss the root operational causes that drive
ongoing ticket volume.
```

Stronger:

```text
Dashboards can show the repeat. They often miss the cause.
```

## Human Interest Rules

A robotic draft talks about:

- systems
- workflows
- insights
- optimization
- platforms
- processes

A human draft talks about:

- customers
- agents
- founders
- support leads
- the team
- the person waiting for an answer

Use people words when they are true:

- "The customer asks again."
- "The agent answers again."
- "The support lead sees the volume."
- "Product may own the fix."
- "Billing may need to review the workflow."

Do not add fake intimacy. Plain Talk is direct, not sentimental.

## Resolution Audit Plain Talk Rules

Use these product-specific rules:

- Say "the same question comes back" before saying "repeat volume."
- Say "cost exposure" only after explaining what is being counted.
- Say "probable owner lane" only if you also explain that ownership is not
  certain.
- Say "no proven answer" when the ticket history lacks scoped resolution
  evidence.
- Say "the report points to" instead of "the report proves" unless the source
  evidence is explicit.
- Say "may" when the audit has a signal but not certainty.

## Model Instructions

When asking a model for a Plain Talk rewrite, paste this:

```text
Rewrite the draft in Plain Talk.

Keep the claims guard intact.
Target Flesch Reading Ease 65-80 unless I specify another format.
Use short sentences.
Use common words.
Cut corporate nouns.
Use people words where true: customers, agents, support lead, founder, team,
you, we.
Keep one idea per sentence.
Preserve uncertainty language: may, appears, estimated, probable, when evidence
exists.

Return:
1. The rewritten draft.
2. The three biggest changes you made.
3. Any claim-risk changes you had to preserve.
```

## Final Check

Before posting, ask:

1. Could I say this out loud without cringing?
2. Does each sentence make one point?
3. Did I name the person affected?
4. Did I replace corporate nouns with actions?
5. Did I keep the evidence boundary?
6. Did I avoid sounding like a landing page?

If the answer is no, rewrite once more.
