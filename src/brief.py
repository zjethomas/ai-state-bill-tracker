"""Render classified bills into a weekly markdown brief for a state Governor's
Office policy adviser -- someone with a few minutes to scan it, not a
technical audience.

Each bill gets a short plain-English summary generated from its Open States
digest/abstract (never the raw abstract text verbatim -- see _summarize_bill).
Summaries are computed once per unique bill, not once per category a bill
appears in, so a bill matching three categories doesn't triple the API cost.
"""

import datetime
import os
import time

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"
REQUEST_DELAY_SECONDS = 1.0
MAX_SUMMARY_TOKENS = 350

STATE_NAMES = {
    "CA": "California",
    "NY": "New York",
    "UT": "Utah",
}

_BASIS_NOTES = {
    "digest/abstract": "*(Summary based on the official digest/abstract.)*",
    "unavailable": "*(No bill text was available yet from Open States -- summary not generated.)*",
    "error": "*(Automated summary generation failed -- read the source directly.)*",
}


def _state_name(code: str) -> str:
    return STATE_NAMES.get(code, code)


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return anthropic.Anthropic(api_key=api_key)


def _summarize_bill(bill: dict) -> tuple[str, str]:
    """Generate a 1-2 sentence plain-English summary of one bill.

    Returns (summary_text, basis), where basis is one of:
      "digest/abstract" -- summarized from the official Open States abstract
      "unavailable"      -- no bill text was available; no API call was made
      "error"            -- the API call failed twice; summary_text explains why

    Never fabricates a summary from the title alone -- if there's no text,
    that's stated plainly rather than presenting a thin, falsely-confident
    summary (per project design).
    """
    if not bill.get("text_available") or not bill.get("text"):
        return (
            "No official digest or bill text was available from Open States "
            "when this brief was generated.",
            "unavailable",
        )

    prompt = (
        "Summarize what this bill actually does in 1-2 plain-English sentences "
        "for a busy state Governor's Office policy adviser. No jargon, no legal "
        "boilerplate, don't just restate the title. Be concrete about what "
        "changes if the bill passes.\n\n"
        "Write ONLY those 1-2 sentences. Do not add caveats, disclaimers about "
        "what the digest doesn't specify, open questions for the reader, or any "
        "other commentary -- if the digest is thin on detail, just summarize "
        "what it does say, plainly.\n\n"
        f"Title: {bill.get('title') or '(no title)'}\n"
        f"Official digest/abstract: {bill['text']}"
    )

    last_error = None
    for attempt in (1, 2):
        try:
            client = _get_client()
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_SUMMARY_TOKENS,
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("summary request was refused")
            if response.stop_reason == "max_tokens":
                raise RuntimeError("summary response was truncated (hit max_tokens)")
            text = next((b.text for b in response.content if b.type == "text"), None)
            if not text or not text.strip():
                raise RuntimeError("no text content in summary response")
            return (text.strip(), "digest/abstract")
        except Exception as exc:
            last_error = exc
            print(f"[brief]   summary attempt {attempt}/2 failed for bill {bill.get('bill_id', '?')}: {exc}")
            if attempt == 1:
                time.sleep(REQUEST_DELAY_SECONDS)

    return ("Summary unavailable -- generation failed after retry.", "error")


def _summarize_all(classified_bills: list[dict]) -> dict:
    """Summarize every unique bill once. Returns {(state, bill_id): (text, basis)}."""
    print(f"[brief] summarizing {len(classified_bills)} bill(s)...")
    summaries = {}
    total = len(classified_bills)
    for i, entry in enumerate(classified_bills):
        bill = entry["bill"]
        key = (bill.get("state"), bill.get("bill_id"))
        summaries[key] = _summarize_bill(bill)
        if i < total - 1:
            time.sleep(REQUEST_DELAY_SECONDS)
    return summaries


def _format_date(week_of: str) -> str:
    try:
        return datetime.date.fromisoformat(week_of).strftime("%B %-d, %Y")
    except ValueError:
        return week_of


def _bill_block(entry: dict, summaries: dict, *, review_context: bool = False) -> str:
    bill = entry["bill"]
    classification = entry["classification"]
    key = (bill.get("state"), bill.get("bill_id"))
    summary_text, basis = summaries.get(key, ("Summary unavailable.", "error"))

    bill_id = bill.get("bill_id") or "?"
    title = bill.get("title") or "(untitled)"
    header = f"**{bill_id}** -- {title}"
    if classification["needs_human_review"] and not review_context:
        header += "  ⚠️ *flagged for review -- see Needs Review section*"

    lines = [header, summary_text]
    basis_note = _BASIS_NOTES.get(basis)
    if basis_note:
        lines.append(basis_note)

    if review_context:
        matched = ", ".join(c["id"] for c in classification["categories"]) or "none matched"
        reason = classification.get("review_reason") or "no reason recorded"
        confidence = classification.get("confidence") or "unknown"
        lines.append(f"Reason: {reason} (confidence: {confidence}). Categories considered: {matched}.")
    else:
        status = bill.get("latest_action") or "No action recorded yet."
        lines.append(f"Latest action: {status}")

    source = bill.get("source_url")
    if source:
        lines[-1] += f" · [source]({source})"

    return "  \n".join(lines)


def _group_by_state(entries: list[dict], states: list[str]) -> dict:
    grouped: dict = {s: [] for s in states}
    for entry in entries:
        grouped.setdefault(entry["bill"].get("state"), []).append(entry)
    return grouped


def _footer(states: list[str], week_of: str) -> str:
    state_names = ", ".join(_state_name(s) for s in states)
    return (
        "---\n\n"
        f"*This run covered {state_names}, current legislative session, as of "
        f"{week_of}. This is an automated screening tool, not a substitute for "
        "reading the full bill.*"
    )


def render_brief(classified_bills: list[dict], categories: list[dict], states: list[str], week_of: str) -> str:
    """Render classified, relevant bills into a markdown brief.

    Inputs:
        classified_bills: {"bill": {...}, "classification": {...}} dicts,
            the output of src/classify.py's classify_bills.
        categories: The taxonomy from config.yaml's `categories` list, in
            taxonomy order -- bills are grouped into sections in this order.
        states: The tracked state codes from config.yaml's `states` list,
            e.g. ["CA", "NY", "UT"] -- used to report per-state coverage,
            including states that returned zero bills this run.
        week_of: ISO date string (e.g. "2026-07-27") identifying the brief.

    Output:
        A single markdown string: header with run stats, one section per
        taxonomy category with >=1 matching bill (empty categories are
        skipped -- no empty heading -- but still listed in a one-line note),
        bills within each category grouped by state, and a closing "Needs
        Review" section listing every bill classify.py flagged, with why.
        A state with zero bills this run is called out plainly in the
        header rather than just silently missing from every section.

    Failure behavior:
        - An empty classified_bills list produces a valid brief saying no
          relevant AI bills were found, not an error.
        - Per-bill summary generation retries once on failure and falls
          back to a visible "summary unavailable" note rather than
          crashing the whole brief or silently omitting the bill.
    """
    summaries = _summarize_all(classified_bills)

    lines = [
        "# AI State Bill Tracker -- Weekly Brief",
        "",
        f"**Generated:** {_format_date(week_of)}  ",
        f"**States covered:** {', '.join(_state_name(s) for s in states)}  ",
        f"**Total bills this run:** {len(classified_bills)}",
        "",
    ]

    bills_by_state = _group_by_state(classified_bills, states)
    lines.append(
        "**Bills by state:** "
        + " · ".join(f"{_state_name(s)} -- {len(bills_by_state[s])}" for s in states)
    )
    lines.append("")
    for s in states:
        if not bills_by_state[s]:
            lines.append(f"> **{_state_name(s)}:** no bills matched this run.")
    lines.append("")

    if not classified_bills:
        lines.append("No relevant AI bills were found across the tracked states this week.")
        lines.append("")
        lines.append(_footer(states, week_of))
        return "\n".join(lines)

    bills_by_category: dict[str, list[dict]] = {c["id"]: [] for c in categories}
    for entry in classified_bills:
        for cat in entry["classification"]["categories"]:
            if cat["id"] in bills_by_category:
                bills_by_category[cat["id"]].append(entry)

    lines.append("---")
    lines.append("")

    zero_categories = []
    for cat in categories:
        entries = bills_by_category[cat["id"]]
        if not entries:
            zero_categories.append(cat["label"])
            continue

        lines.append(f"## {cat['label']} ({len(entries)})")
        lines.append("")
        for s, state_entries in _group_by_state(entries, states).items():
            if not state_entries:
                continue
            lines.append(f"### {_state_name(s)}")
            lines.append("")
            for entry in state_entries:
                lines.append(_bill_block(entry, summaries))
                lines.append("")
        lines.append("---")
        lines.append("")

    if zero_categories:
        lines.append(f"*No bills this run in: {', '.join(zero_categories)}.*")
        lines.append("")

    review_entries = [e for e in classified_bills if e["classification"]["needs_human_review"]]
    lines.append(f"## ⚠️ Needs Review ({len(review_entries)})")
    lines.append("")
    lines.append(
        "These bills weren't confidently categorized by the automated pipeline "
        "-- read them directly rather than relying on the category tags above."
    )
    lines.append("")
    if not review_entries:
        lines.append("None this run.")
        lines.append("")
    else:
        for s, state_entries in _group_by_state(review_entries, states).items():
            if not state_entries:
                continue
            lines.append(f"### {_state_name(s)}")
            lines.append("")
            for entry in state_entries:
                lines.append(_bill_block(entry, summaries, review_context=True))
                lines.append("")

    lines.append(_footer(states, week_of))
    return "\n".join(lines)
