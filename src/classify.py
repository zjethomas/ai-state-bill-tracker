"""Classify a bill into one or more categories of the AI-policy taxonomy via Claude.

Uses structured JSON output (output_config.format) so the response is
guaranteed to parse and match our schema, with the category `id` field
constrained to the taxonomy's actual category ids so Claude can't invent one.
Thinking is disabled to keep a ~150-bill/week classification run fast and
cheap -- this is a bounded classification task with no tool use, so the
tool-call-as-text failure mode that normally argues against disabling
thinking doesn't apply here.
"""

import json
import os
import time

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"
REQUEST_DELAY_SECONDS = 1.0  # conservative pacing between calls; no documented limit hit yet
MAX_OUTPUT_TOKENS = 1024

# Message fragments that mark a 400 as a billing/quota problem specifically,
# as opposed to some other bad request (e.g. a schema issue on our side).
_BILLING_ERROR_KEYWORDS = ("credit balance", "insufficient credit", "billing", "quota exceeded", "purchase credits")


class AccountLevelAPIError(Exception):
    """A persistent, account-level API failure (out of credits, billing/quota
    problem, bad or revoked credentials) -- as opposed to a transient one
    (timeout, rate limit, momentary server error) that a retry might fix.
    Raised by classify_bill to tell classify_bills to stop the run instead
    of grinding through every remaining bill with the same doomed retry.
    """


def _is_account_level_error(exc: Exception) -> bool:
    """True for errors a per-bill retry can never fix: bad/missing
    credentials (401), no permission to bill (403), or a 400 whose message
    specifically indicates an out-of-credits/quota account. False for
    everything else (rate limits, server errors, network blips, or a 400
    that isn't about billing) -- those keep the existing retry-then-move-on
    behavior, since a retry might genuinely succeed.
    """
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return True
    if isinstance(exc, anthropic.BadRequestError):
        message = str(exc).lower()
        return any(keyword in message for keyword in _BILLING_ERROR_KEYWORDS)
    return False


_RESPONSE_SCHEMA_TEMPLATE = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},  # enum filled in per-call from the taxonomy
                    "justification": {"type": "string"},
                },
                "required": ["id", "justification"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["categories", "confidence"],
    "additionalProperties": False,
}


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return anthropic.Anthropic(api_key=api_key)


def _build_schema(category_ids: list[str]) -> dict:
    schema = json.loads(json.dumps(_RESPONSE_SCHEMA_TEMPLATE))
    schema["properties"]["categories"]["items"]["properties"]["id"]["enum"] = category_ids
    return schema


def _build_prompt(bill: dict, categories: list[dict]) -> str:
    taxonomy_lines = "\n".join(f"- {c['id']}: {c['label']}" for c in categories)
    text = bill.get("text") or "(no bill text available -- classify from the title alone)"
    return (
        "You are classifying a US state legislative bill into an AI-policy taxonomy "
        "for a state Governor's Office tracking AI-related legislation.\n\n"
        f"Taxonomy:\n{taxonomy_lines}\n\n"
        f"Bill title: {bill.get('title') or '(no title)'}\n"
        f"Bill text/abstract: {text}\n\n"
        "Pick every category the bill substantively belongs to -- a bill can match "
        "more than one. For each category you pick, give a one-sentence justification "
        "tied to specific content in the bill. Then give an overall confidence level "
        "(high/medium/low) for this classification as a whole. Use 'low' whenever the "
        "bill is ambiguous, could plausibly fit categories you didn't pick, or you're "
        "relying on the title alone because no bill text was available."
    )


def _call_and_parse(bill: dict, categories: list[dict], category_ids: list[str], schema: dict) -> dict:
    """One classification attempt. Raises on any failure -- API error, refusal,
    or a response that doesn't parse/validate against the taxonomy."""
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        thinking={"type": "disabled"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": schema},
        },
        messages=[{"role": "user", "content": _build_prompt(bill, categories)}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("classification request was refused")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError("no text content in classification response")

    parsed = json.loads(text)
    if "categories" not in parsed or "confidence" not in parsed:
        raise ValueError("response missing 'categories' or 'confidence'")
    for cat in parsed["categories"]:
        if cat["id"] not in category_ids:
            raise ValueError(f"response used unknown category id {cat['id']!r}")
    if parsed["confidence"] not in ("high", "medium", "low"):
        raise ValueError(f"response used invalid confidence {parsed['confidence']!r}")

    return parsed


def classify_bill(bill: dict, categories: list[dict]) -> dict:
    """Classify a single bill into the AI-policy taxonomy via Claude.

    Inputs:
        bill: A bill record that has already passed the relevance gate
            (src/relevance.py), with at least "title" and "text".
        categories: The taxonomy from config.yaml's `categories` list, each
            entry shaped like {"id": ..., "label": ...}.

    Output:
        A dict shaped like:
            {
                "categories": [{"id": ..., "justification": "..."}, ...],
                "confidence": "high" | "medium" | "low" | None,
                "needs_human_review": bool,
                "review_reason": str | None,
            }
        A bill may match more than one category. needs_human_review is True
        whenever the model reports "low" confidence, no category matched at
        all, or classification failed outright after a retry -- low
        confidence is surfaced, not silently treated as a clean result.

    Failure behavior:
        Transient failures (network error, refused request, a response
        that fails to parse/validate) are retried once. If the retry also
        fails, this does NOT raise -- it returns a result with
        needs_human_review=True and review_reason explaining the failure,
        so one bad bill can't crash the whole run.

        Persistent, account-level failures (out of credits, billing/quota
        problem, bad or revoked credentials -- see
        _is_account_level_error) are NOT retried, since a retry is
        guaranteed to fail the same way. Instead this raises
        AccountLevelAPIError immediately, so the caller (classify_bills)
        can stop the run rather than grinding through every remaining
        bill with the same doomed call.

        Requires ANTHROPIC_API_KEY in the environment (see .env.example).
    """
    category_ids = [c["id"] for c in categories]
    schema = _build_schema(category_ids)

    last_error = None
    parsed = None
    for attempt in (1, 2):
        try:
            parsed = _call_and_parse(bill, categories, category_ids, schema)
            break
        except Exception as exc:
            if _is_account_level_error(exc):
                raise AccountLevelAPIError(str(exc)) from exc
            last_error = exc
            print(f"[classify]   attempt {attempt}/2 failed for bill {bill.get('bill_id', '?')}: {exc}")
            if attempt == 1:
                time.sleep(REQUEST_DELAY_SECONDS)

    if parsed is None:
        return {
            "categories": [],
            "confidence": None,
            "needs_human_review": True,
            "review_reason": f"classification failed after retry: {last_error}",
        }

    confidence = parsed["confidence"]
    needs_review = confidence == "low" or not parsed["categories"]
    review_reason = None
    if needs_review:
        review_reason = (
            "model reported low confidence" if confidence == "low" else "no category matched"
        )

    return {
        "categories": parsed["categories"],
        "confidence": confidence,
        "needs_human_review": needs_review,
        "review_reason": review_reason,
    }


def classify_bills(bills: list[dict], categories: list[dict]) -> list[dict]:
    """Classify a full list of relevant bills and report a summary.

    Input:
        bills: Bills that passed src/relevance.py's filter_relevant_bills.
        categories: The taxonomy from config.yaml's `categories` list.

    Output:
        A list of {"bill": bill, "classification": classify_bill result}
        dicts, one per input bill in order -- matching the shape
        src/brief.py's render_brief expects. Every bill is returned,
        including ones whose classification failed (they carry
        needs_human_review=True instead of being dropped).

    Side effects:
        Prints a summary: total classified, a count per taxonomy category,
        and how many were flagged needs_human_review, so a human can
        sanity-check the results before trusting them downstream.

    Failure behavior:
        Does not raise on a single bill's transient classification failure
        -- see classify_bill. Paces requests with REQUEST_DELAY_SECONDS
        between calls to stay well under rate limits.

        On a persistent, account-level failure (classify_bill raises
        AccountLevelAPIError -- out of credits, billing/quota problem, bad
        credentials), stops immediately instead of repeating the same
        doomed call for every remaining bill: prints a clear message
        naming how many bills got through before it happened, then
        returns just those already-classified bills rather than raising
        further, so the pipeline can still produce a brief from partial
        results instead of losing everything.
    """
    results = []
    for i, bill in enumerate(bills):
        try:
            classification = classify_bill(bill, categories)
        except AccountLevelAPIError as exc:
            remaining = len(bills) - len(results)
            print(
                f"[classify] STOPPED: Anthropic API reports a persistent account-level "
                f"error ({exc}). {len(results)} of {len(bills)} bills were classified "
                f"before this occurred -- not retrying the remaining {remaining} bill(s), "
                "since this kind of failure won't resolve itself bill by bill."
            )
            break
        results.append({"bill": bill, "classification": classification})
        if i < len(bills) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

    total = len(results)
    needs_review_count = sum(1 for r in results if r["classification"]["needs_human_review"])
    category_counts: dict[str, int] = {}
    for r in results:
        for cat in r["classification"]["categories"]:
            category_counts[cat["id"]] = category_counts.get(cat["id"], 0) + 1

    print(f"[classify] classified {total} bill(s); {needs_review_count} flagged needs_human_review")
    print("[classify] counts per category:")
    for cat in categories:
        print(f"[classify]   {cat['id']}: {category_counts.get(cat['id'], 0)}")

    return results
