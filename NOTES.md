# Build log

Running notes on decisions, failures, and changes as this gets built.
Newest entries at the bottom.

## 2026-07-26

Scaffold created.

Implemented `src/fetch.py` against the real Open States v3 API. Notes from
building it against live data:

- **Session resolution.** The API has no "current session" flag. Resolved
  it by pulling each jurisdiction's `legislative_sessions` and picking the
  one with the latest `start_date` that isn't in the future (ties broken
  toward non-special sessions). Verified against real data: CA -> 20252026,
  NY -> 2025-2026, UT -> 2026. UT already lists a `2027` session with a
  future start date, which the "not in the future" check correctly skips.
- **"Pending" is a heuristic, not an API field.** Open States doesn't
  expose bill status directly, only free-text `latest_action_description`.
  Built a keyword filter, then found by inspecting real responses that
  wording differs a lot by state: CA writes "Chaptered by Secretary of
  State", UT writes "Governor Signed" (note the reversed word order vs.
  "signed by governor" — the first keyword list missed this and
  undercounted UT's non-pending bills), NY uses bill-tracking jargon like
  "APPROVAL MEMO.76" (= signed) and "ENACTING CLAUSE STRICKEN" (= killed
  without a floor vote). Current keyword list covers all three states'
  observed terminology plus a general "governor" + "sign" check. Known
  gap: NY's "ADOPTED" is ambiguous (could mean a resolution passed —
  terminal — or an amendment was adopted — not terminal) and isn't
  filtered; left as a false negative rather than risk false positives.
- **Rate limit.** Free tier rejects bursts well before any documented
  number — hit HTTP 429 at roughly 1 request/second. Settled on a 6.5s
  delay between requests (under ~10/min) plus a longer 20s backoff
  specifically on a 429 before the single retry.
- **Bill text.** The API returns an `abstracts` field (legislative
  summary) via `include=abstracts`, not full bill text inline — full text
  is only available as linked PDFs (`versions`/`documents`). Using the
  abstract as `text`, with `text_available: False` when a bill has none
  yet (typical for just-introduced bills).

Live sanity check (2026-07-26, current sessions): CA 43 pending bills, NY
189, UT 13, all after the pending-keyword fix above. Sample record and
counts shown to the user for review before wiring up classify.py.

Implemented `src/relevance.py`, the gate that drops bills where AI is only
an incidental mention. First draft used rigid exact-phrase matching (e.g.
`"automated decision system"`, `"deepfakes"`, a flat "2+ mentions" rule)
and a live run against all three states' pending bills showed it was
dropping bills a Governor's office would clearly want to see:

- A NY bill requiring "responsible capability scaling policies" (a
  frontier-model-safety bill, i.e. exactly what the `frontier_foundation_models`
  category exists for) was dropped because its abstract mentions AI only
  once. The abstract is one sentence, entirely about that one bill — a
  single mention there is a strong signal, not a passing reference.
- Several clearly-relevant automated-decision bills were dropped because
  real titles paraphrase instead of using the exact phrase "automated
  decision system": "automated lending decision-making tools", "automated
  employment decision tools", "automated decision tools by landlords".
- A deepfake bill was dropped because its text says "deep fakes" (two
  words), which the "deepfake" pattern didn't match.
- A "synthetic content creations system" provenance-disclosure bill and
  several "synthetic performer" disclosure bills were dropped because the
  pattern only covered the exact phrase "synthetic media".

Fixed by: (1) using proximity regex ("automated"/"automatic" within ~40
chars of "decision", "synthetic" within ~30 chars of
content/media/performer/voice/actor/image/video) instead of rigid exact
phrases; (2) adding "machine learning" as an explicit AI-specific concept;
(3) making the single-generic-mention rule length-aware — one mention of
"AI"/"artificial intelligence" now passes if the abstract is short (<=300
chars, roughly one or two sentences, so that one mention is most of what
the abstract says), and still requires 2+ mentions for longer text. This
matters because the *correct* drops in the same run were giant omnibus
budget bills (thousands of characters, dozens of unrelated programs) that
happened to mention AI once — exactly the incidental-mention case the gate
exists to catch. Length turned out to be the signal that told these two
cases apart.

Re-ran after the fix: CA 43 -> 28, NY 189 -> 115, UT 13 -> 3. All previously
wrong drops now pass; no new obviously-wrong passes spotted on a manual
read of the NY dropped list.

Known, accepted gaps (leaning toward dropping on ambiguous cases, per the
"be strict" instruction):
- Bare "algorithmic ___" (algorithmic pricing, algorithmic wage-setting,
  "office of algorithmic innovation") is NOT treated as AI-specific on its
  own — deterministic rule-based algorithms aren't necessarily AI, and
  broadening this pattern risked pulling in unrelated bills. These stay
  dropped unless the bill also uses "AI"/"artificial intelligence"/one of
  the other concept terms.
- Deepfake-adjacent bills that use euphemisms with no "synthetic" or
  "deepfake" wording at all (e.g. NY's "unlawful dissemination ... of a
  fabricated photographic, videographic, or audio record") aren't caught.
  Chasing every possible phrasing risks unreadable regex; flagging this as
  a known miss instead.
- UT bills almost never have abstract text from Open States (0/13 in this
  run) — UT recall is capped at title-only matching, so a real UT AI bill
  with a generic short title (e.g. "Educational Technology Regulatory
  Sandbox") won't pass unless "AI" is literally in the title. This is a
  data-availability limitation, not a logic bug.

Added an 8th taxonomy category, `data_centers` (config.yaml), and a second,
independent pass-path for it in `judge_relevance`
(`_judge_data_center_relevance`). Data center siting/construction fights
(bans, moratoriums, new permitting restrictions on facilities over 50MW)
are a live state policy fight distinct from AI-model regulation, but
Arizona-relevant given data center growth in-state — a bill can now pass
the gate on this basis alone even with zero AI content. Deliberately
narrow per instruction: requires "data center(s)" plus either a MW/
megawatt size threshold, construction/siting language near the mention, or
a moratorium/ban/restriction word — mentioning "data center" alone (a
cybersecurity bill, a tax-incentive bill listing data centers as a
covered industry) does not qualify. This path only runs as a fallback,
after the AI-based rules find nothing, and gets its own "passed: data
center ..." reason string so these passes are auditable separately from
AI-keyword passes.

Live re-run: CA 43->28, NY 189->117 (+2 vs. the AI-only gate), UT 13->3.
Exactly 2 bills passed via this rule alone: NY's A 10141 / S 9144 (the
same bill filed in both chambers), "Imposes a moratorium on data center
permit issuance". Sanity-checked against the two CA/NY bills that mention
"data center" without a construction angle ("Data centers: power usage
effectiveness: cost shifts" and "data center water stewardship and reuse
act") — both correctly still drop, confirming the rule isn't just matching
on the word "data center". One open question for review: the two passing
bills don't actually state a MW threshold in their abstract (a blanket
moratorium on "new data centers", not specifically ones over 50MW) — they
passed on the moratorium/restriction signal alone, per the instruction
that a ban/moratorium is sufficient on its own. Worth confirming this is
the intended scope, since the category's stated definition is "over
50MW" specifically.

Resolved the above: user confirmed the MW/megawatt figure should be
required, not just a moratorium/restriction word. Updated
`_judge_data_center_relevance` to require the size-threshold pattern as a
mandatory `AND` condition alongside construction/siting or restriction
language. Re-verified the NY moratorium bill (no stated MW figure) now
correctly drops. Live counts weren't re-confirmed end-to-end after this
change because Open States started 429ing (see below), but the specific
bill that motivated the change was independently re-checked as correct in
two separate partial runs before committing.

Implemented `src/classify.py` against the real Anthropic API. Design:

- **Structured JSON output** (`output_config.format` with a `json_schema`)
  rather than free-text parsing, with the category `id` field's enum
  constrained per-call to the taxonomy's actual ids from config.yaml — so
  Claude can't invent a category that doesn't exist.
- **Thinking disabled** (`thinking: {type: "disabled"}`) to keep a
  ~150-bill/week run fast and cheap. This is a bounded classification task
  with no tool use, so the "tool call written as text instead of a real
  tool_use block" failure mode that normally argues against disabling
  thinking on Claude Opus 5 doesn't apply here.
- **Retry-once-then-fallback**, mirroring fetch.py's pattern: any failure
  (API error, refusal, a response that fails to parse or uses an unknown
  category id) retries once; if that also fails, the bill gets
  `needs_human_review: true` with the error as `review_reason` instead of
  crashing the run.
- **Confidence is a single overall high/medium/low per bill**, not a
  per-category float — matches this task's explicit spec, which
  supersedes the original stub's per-category-confidence sketch.
  `needs_human_review` is set whenever confidence is "low" or zero
  categories matched.
- Model is `claude-opus-5` per the project's Claude API guidance (always
  default to Opus unless told otherwise). Effort is `medium` — a
  deliberate cost/quality tradeoff for a bulk classification task, not a
  quality problem being worked around.

Validation: a single-bill smoke test passed cleanly (CA SB 1106, correctly
tagged agentic_ai + sector_health_gov_use). For the fuller sanity check,
Open States returned 429 on every request starting ~2026-07-26 23:39 UTC
(16:39 local) — confirmed via 4 retries with 20s waits in between, which
ruled out the per-minute burst limit from earlier fetch.py work (that
clears within seconds). Checked the actual response body directly with
curl, which confirmed it's a **daily** quota, not a burst limit:

    HTTP/2 429
    {"detail":"exceeded limit of 250/day: 265"}

265 requests against a 250/day cap, run up over the course of this
session's repeated fetch.py/relevance.py testing (each fetch run makes a
handful of paginated + jurisdiction-lookup calls per state, and there were
many runs today). Confirms `src/fetch.py`'s free-tier assumption in the
earlier NOTES entry (~10/min) was the wrong constraint to worry about —
the daily cap is the one that actually bit us. Doesn't need a code change
for classify.py's sake (that module doesn't call Open States at all), but
worth flagging for fetch.py: the weekly GitHub Action only needs ~15-20
Open States calls per run, comfortably under 250/day, so this is purely a
today's-manual-testing problem, not a production risk — noting it here in
case iteration testing needs to pace itself against the same cap again
before the daily reset.

Rather than block on the quota, ran `classify_bills` against 4 bills using
real bill text already pulled from Open States earlier in this session (CA
SB 1106, plus 3 NY bills: the capability-scaling/frontier-model bill, the
synthetic content provenance bill, and the automated lending decision
bill) — genuine bill content, just not a fresh live pull. All 4 classified
sensibly with 0 flagged for review; results shown to the user for review.

What surprised me: SB 1106 (agentic AI amendments to an existing risk
analysis and inventory law) got tagged with 4 categories including
`frontier_foundation_models` at only "medium" confidence, justified by a
mention of "generative artificial intelligence" and "mass casualty
events" that's actually describing *existing law* the bill amends, not
something the bill itself newly regulates. Arguably over-inclusive — worth
watching for this pattern (tagging a category based on background/context
language in the abstract rather than what the bill itself changes) once
classifying the full weekly batch, not just this small sample.

TODO before trusting classify.py at full scale: re-run `classify_bills`
against a fresh, complete fetch -> relevance batch once Open States'
quota resets, to get real per-category counts across all pending bills
(the 4-bill sample above is a quality spot-check, not a representative
distribution).

## 2026-07-27

Ran the full fetch -> relevance -> classify pipeline end to end, all
three states, complete bill sets (Open States' daily quota had reset).
First attempt hit a mid-pagination read timeout on UT (only 4/13 bills
fetched before fetch.py's retry gave up and moved on, per its designed
failure behavior); re-ran UT alone to get the complete 13, then re-ran
relevance + classify against the merged CA + NY + UT set so the final
numbers reflect the complete bill set, not a partial one.

**Fetch -> relevance, per state:**

| State | Fetched (pending) | Passed relevance gate |
|---|---:|---:|
| CA | 43 | 28 |
| NY | 189 | 115 |
| UT | 13 | 3 |
| **Total** | **245** | **146** |

**Classification (146/146 bills, 0 API failures/retries):**

| Category | Count |
|---|---:|
| sector_health_gov_use | 71 |
| automated_decision_making | 63 |
| deepfakes_synthetic_media | 31 |
| ai_data_privacy | 21 |
| chatbot_companion_disclosure | 24 |
| frontier_foundation_models | 23 |
| agentic_ai | 5 |
| data_centers | 1 |

(Categories sum to more than 146 since a bill can match more than one.)

**needs_human_review: 23/146 total** (CA 4, NY 16, UT 3) — flagged
whenever the model reported "low" confidence or matched zero categories;
not yet manually reviewed, just surfaced per classify.py's design.

Sanity check on category distribution: `sector_health_gov_use` and
`automated_decision_making` dominating makes sense given the taxonomy and
what's actually moving right now (a lot of pending bills are about
automated decision tools in employment/lending/housing, or general
government AI-use provisions) — not an obviously wrong skew. `agentic_ai`
(5) and `data_centers` (1) being the smallest categories also tracks: those
are newer, narrower policy areas with fewer bills filed so far this
session. Haven't done a manual spot-check of the 23 needs_human_review
bills yet -- that's the natural next step before trusting this brief
output at face value.

Implemented `src/brief.py`. Design:

- Groups bills by taxonomy category (config.yaml order), skipping any
  category with zero bills this run -- no empty heading -- but still
  naming skipped categories in a one-line note so a zero result is never
  silently invisible. Within a category, bills are grouped by state.
- Per-bill: bill number + title, a 1-2 sentence plain-English summary,
  latest action, and a source link. Every summary is labeled with its
  basis (official digest/abstract, no text available, or generation
  failed) -- never presented as if it were more authoritative than it is.
- Header reports total bills and a per-state breakdown; any tracked state
  with zero bills gets an explicit "no bills matched this run" callout
  rather than just being absent from every section (the designed
  zero-result edge case).
- A bill flagged `needs_human_review` by classify.py gets an inline
  ⚠️ marker wherever it appears in a category section, plus full detail
  (reason, confidence, categories considered) in a dedicated "Needs
  Review" section at the end.
- Summaries are generated by brief.py itself (a separate, lighter Claude
  call per bill -- no JSON schema needed for a plain sentence or two;
  thinking disabled, effort low), not folded into classify.py's call.
  Keeps the two modules single-purpose: classify.py tags categories,
  brief.py explains bills to a human. Computed once per unique bill and
  cached, even though a bill can appear in multiple category sections plus
  the Needs Review section -- avoids N-times the API cost for a bill
  matching N categories.

Bug found and fixed during the first real run: `MAX_SUMMARY_TOKENS` was
200, and the model routinely ran past the requested "1-2 sentences" into
unsolicited caveats ("Note: the digest doesn't specify...", "Two things
worth flagging for the Governor's Office: ...") -- long enough that many
responses hit the token cap and got cut off mid-word in the rendered
brief (99 of 262 summary occurrences were truncated, no terminal
punctuation). Fixed two ways: (1) the prompt now explicitly says write
*only* the 1-2 sentences, no caveats or open questions; (2) raised the
cap to 350 tokens as a safety margin; (3) added a check on
`response.stop_reason == "max_tokens"` so a truncated response is now
treated as a failure that retries and falls back to a visible "summary
unavailable" note, instead of silently accepting cut-off text. Re-ran:
0/119 successful summaries truncated after the fix (down from 99/262).

**Currently blocked:** the Anthropic account ran out of API credits
partway through the second (fixed) run -- "Your credit balance is too low
to access the Anthropic API." Of 146 bills, only 62 got a real generated
summary before hitting this; the other 80 correctly show the "Summary
unavailable -- generation failed after retry" fallback (the retry-then-
fallback logic worked exactly as designed -- it didn't crash the run or
silently drop bills), but the brief itself is incomplete as a result. This
is a today's-cumulative-usage problem (relevance/classify testing +
two brief.py passes over ~140 bills each), not a code bug. Also cleaned up
the fallback text while investigating: it was dumping the raw exception
object (including request_id) into the reader-facing brief, which is bad
UX regardless of the credits issue -- the console log stays verbose for
debugging, the brief-facing text is now a short, clean sentence.

`output/2026-07-27-brief.md` as committed right now is this degraded,
partial-credit-failure version -- needs a clean re-run once the account
has credits again before this is genuinely ready for review.

Patched `src/classify.py` to distinguish transient API failures from
persistent, account-level ones, prompted directly by the real
credit-exhaustion incident above. That incident happened during
brief.py's summarization pass (62 of 146 bills got a real summary before
the account ran dry) -- classify.py's own run earlier that same day
completed cleanly with zero failures, before credits ran out. So this is
a proactive fix, not a fix for a failure classify.py has hit live yet: the
same account-level condition will hit classify.py's own API calls next
time credits run low mid-run, and before this fix it would have handled
that exactly like brief.py's old behavior -- retrying once per bill, then
grinding through every remaining bill with the same doomed call, each one
landing in needs_human_review with a confusing per-bill error message
instead of one clear "the account is out of credits" signal.

Added `_is_account_level_error()`: True for 401 (`AuthenticationError`)
and 403 (`PermissionDeniedError`) unconditionally, and for a 400
(`BadRequestError`) specifically when its message mentions billing/credit
keywords ("credit balance", "insufficient credit", "billing", "quota
exceeded", "purchase credits") -- a generic 400 for some other reason
(e.g. a genuinely malformed request) still falls through to the existing
transient-retry path, since only the billing-flavored 400 is guaranteed
non-recoverable. Rate limits (429) and server errors (5xx) are
deliberately NOT treated as account-level, per the requirement -- those
stay on the existing retry-once-then-continue path since a retry might
actually succeed.

On a detected account-level error, `classify_bill` now raises a new
`AccountLevelAPIError` immediately -- no wasted retry, since the same
account-level condition won't resolve itself one second later.
`classify_bills` catches it, prints a clear stop message naming exactly
how many bills got through before it happened, and returns those
already-classified bills instead of raising further -- so main.py's
pipeline can still proceed to brief.py and produce a brief from partial
results rather than losing the whole run.

Verified without spending any real API credits or waiting for the account
to run dry again: constructed a real `anthropic.BadRequestError` locally
(via a fake `httpx.Response` carrying the actual billing message text
Anthropic returned yesterday) and monkeypatched `_call_and_parse` to
raise it on the 3rd of 5 fake bills. Confirmed: exactly 3 calls made (no
wasted retry on the billing error itself), the run stopped immediately
rather than continuing through bills 4-5, and `classify_bills` returned
the 2 successfully-classified bills rather than raising or losing them.
Separately confirmed the transient path is unchanged: a fake transient
error still retries once, then continues to the next bill with
needs_human_review=True, exactly as before.
