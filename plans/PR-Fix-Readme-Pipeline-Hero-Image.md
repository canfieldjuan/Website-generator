# PR: Fix-Readme-Pipeline-Hero-Image

## Why this slice exists

The README (added in PR #22) contains an incorrect description of the
redesign pipeline's hero-image step:

> **Hero image** — tries Unsplash first (free, if `UNSPLASH_ACCESS_KEY`
> is set), falls back to Flux generation via OpenRouter
> (`black-forest-labs/flux.2-max`).

`pipeline.py` does not call `fetch_unsplash_hero` at any point (grep
confirms zero hits for "unsplash" in the file). The Unsplash-first /
Flux-fallback two-path logic lives exclusively in `build.py`. The
redesign pipeline goes straight to `generate_image_openrouter` whenever
hero generation is needed.

This is a P2 accuracy bug: operators who set `UNSPLASH_ACCESS_KEY`
expecting free-photo behavior in the redesign flow will still incur paid
Flux calls with no indication that the key has no effect there.

## Scope (this PR)

1. Correct the hero-image step description in the `pipeline.py`
   architecture section of `README.md`.
2. Add this plan doc.

### Files touched

- `README.md` (one sentence edit)
- `plans/PR-Fix-Readme-Pipeline-Hero-Image.md` (new)

## Mechanism

Replace the incorrect two-path description with the actual single-path
behavior:

- **Before:** "tries Unsplash first (free, if `UNSPLASH_ACCESS_KEY` is
  set), falls back to Flux generation via OpenRouter
  (`black-forest-labs/flux.2-max`)"
- **After:** "Flux-only via `generate_image_openrouter` (OpenRouter,
  `black-forest-labs/flux.2-max`). `UNSPLASH_ACCESS_KEY` has no effect
  in the redesign pipeline — the Unsplash path is `build.py`-only."

The base64-decoding note is preserved because it is accurate.

## Intentional

- No change to `pipeline.py` code — adding an Unsplash path to the
  redesign pipeline would be a feature, not a doc fix. Documenting the
  existing behavior correctly is the right scope here.

## Deferred

- Adding an Unsplash-first path to `pipeline.py` — separate feature
  slice if desired.

## Verification

```bash
# Confirm no unsplash reference in pipeline.py (expect: no output)
grep -i unsplash pipeline.py
# Result: (no output)

# Confirm the corrected line is present
grep -n "Flux-only" README.md
# Expect: line in the pipeline.py hero-image step

# local_pr_review.sh
bash scripts/local_pr_review.sh
# Expect: diff --check PASS, plan-doc presence PASS
```

## Estimated diff size

2 files, +35 / -2. Well within budget.
