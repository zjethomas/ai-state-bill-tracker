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
