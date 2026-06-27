# PR: Resolution Audit Open WebUI Skills

## Why this slice exists

The prompts are useful in Open WebUI, but the model still needs reusable
instruction packs it can load on demand. Prompts are good for one-shot commands.
Skills are better for durable behavior: claim safety, Plain Talk rewrites,
target report-shape explanations, and draft review.

## Scope (this PR)

1. Add paste-ready Open WebUI Skill Markdown files.
2. Keep each skill narrow enough for small local models.
3. Add an index with install and usage guidance.
4. Update the Resolution Audit README to point to the skill pack.

Files touched:

- `content-pipeline/resolution-audit/open-webui-skills/README.md`
- `content-pipeline/resolution-audit/open-webui-skills/claim-guard.md`
- `content-pipeline/resolution-audit/open-webui-skills/content-writer.md`
- `content-pipeline/resolution-audit/open-webui-skills/plain-talk-rewriter.md`
- `content-pipeline/resolution-audit/open-webui-skills/report-shape-router.md`
- `content-pipeline/resolution-audit/open-webui-skills/verifier-reviewer.md`
- `content-pipeline/resolution-audit/README.md`
- `plans/PR-Resolution-Audit-Open-WebUI-Skills.md`

## Mechanism

Each skill is plain Markdown intended for Open WebUI Workspace Skills. The
skills do not fetch files or run code. They instruct the model how to behave
when selected:

- `claim-guard`: prevent unsupported claims.
- `content-writer`: draft channel content using the current offer shape.
- `plain-talk-rewriter`: rewrite without erasing protected terms.
- `report-shape-router`: explain the target before/now report-shape pattern
  without implying owner routing is shipped unless current output confirms it.
- `verifier-reviewer`: use the verifier tool if available, or manually check.

## Intentional

- Skills are concise and composable. Operators can attach only the ones needed
  for a model or use `$skill` inside a chat.
- The verifier skill does not pretend it can call a tool if the tool is not
  enabled.
- Owner routing is framed as target-pattern or data-supported language, not a
  shipped-field claim.
- Skills preserve protected category language instead of simplifying it away.

## Deferred

- Export/import automation for Open WebUI Skills.
- Tool-backed skills that call local scripts directly.

## Verification

Ran locally:

- `rg -n "guaranteed savings|will save|will reduce|auto-publish|automatic help-center|Product owns this|Support failed" content-pipeline/resolution-audit/open-webui-skills`
  - Result: matches only appear in guard/reviewer forbidden-language lists.
- `rg -n "probable owner lane|no proven answer|estimated cost exposure|verify_resolution_audit_draft" content-pipeline/resolution-audit/open-webui-skills`
  - Result: required owner-lane, no-proven-answer, cost-exposure, and verifier
    tool language is present.
- `! rg -n "sales" content-pipeline/resolution-audit/open-webui-skills/verifier-reviewer.md`
- `! rg -n "current report shape|current deliverable|The current report|owner lane is the strategic upgrade|routes repeated issues to a probable owner lane" content-pipeline/resolution-audit/open-webui-skills content-pipeline/resolution-audit/README.md`
- `git diff --check -- content-pipeline/resolution-audit/open-webui-skills content-pipeline/resolution-audit/README.md plans/PR-Resolution-Audit-Open-WebUI-Skills.md`

## Estimated diff size

8 files, +389 / -0. Under the 400 LOC soft cap.
