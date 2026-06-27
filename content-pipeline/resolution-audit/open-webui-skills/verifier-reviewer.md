# Resolution Audit Verifier Reviewer Skill

Use this skill before posting or reusing any Resolution Audit draft.

If the `verify_resolution_audit_draft` tool is available, run it on the draft.

Use:

- `channel`: linkedin, reddit, reply, blog, feedback, or sales
- `asset_id`: a short label for the draft

Return the tool output first, then explain the top revision priorities.

If the tool is not available, say:

```text
The verifier tool is not available in this chat. I will run the manual check.
```

Then run the manual check below.

## Manual Check

Flag:

- guaranteed savings
- guaranteed rankings
- ticket-volume reduction promises
- fixed deflection percentages
- automatic help-center publishing
- automatic ticket answering
- replacing-agent claims
- raw customer data, names, emails, phone numbers, screenshots, or ticket
  excerpts
- answer/draft claims without evidence language
- report-shape explanations that present owner routing as shipped without
  current product output or real audit data
- target report-shape explanations that omit owner routing
- certain ownership claims
- privacy, retention, security, or compliance claims not supplied by the user

## Manual Verdicts

- Safe to post: no obvious blockers, no missing key qualifiers.
- Needs revision: fixable warnings or missing owner routing.
- Do not post: blocker claims, raw private data, or unsupported promises.

## Return Shape

Return verdict, blockers, warnings, missing owner-routing or report-shape
pieces, and suggested revision.
