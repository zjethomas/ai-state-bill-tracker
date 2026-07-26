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
