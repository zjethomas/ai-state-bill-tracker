# Test plan (not yet implemented)

No tests exist yet — this is a placeholder listing the cases we plan to
cover once fetch/relevance/classify/brief have real logic.

- **Normal bill** — a well-formed, clearly AI-related bill with full text
  available; should pass relevance and classify into at least one category
  with reasonable confidence.
- **Bill with no text yet** — pending bill where Open States has a title
  but no posted full text; relevance/classification should degrade
  gracefully (title-only judgment) rather than crash.
- **API timeout** — Open States or Anthropic API call times out; the
  pipeline should surface the failure for that bill/state without aborting
  the whole run.
- **State with zero results** — a tracked state has no AI-related bills
  this session; fetch returns an empty list, and the brief says so instead
  of erroring.
- **Deliberately ambiguous bill** — a bill that plausibly touches two
  categories at low confidence (e.g. mentions both automated
  decision-making and data privacy without clearly regulating either);
  should classify into multiple categories and/or be flagged
  needs_human_review per config.yaml's relevance_threshold.
