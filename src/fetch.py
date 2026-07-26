"""Fetch pending AI-related bills from the Open States v3 API.

Two-step process per state:
  1. Resolve "current" session -> a concrete session identifier, by looking
     at the state's legislative_sessions and picking the most recently
     started one (see _resolve_current_session).
  2. Search /bills for that state+session with q="artificial intelligence",
     paging through all results.

"Pending" is determined heuristically from latest_action_description (see
_TERMINAL_ACTION_KEYWORDS) since the API doesn't expose a status field.
This is a coarse filter, not authoritative -- see NOTES.md.
"""

import os
import time
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://v3.openstates.org"
SEARCH_QUERY = "artificial intelligence"
PER_PAGE = 20  # API max is 20 per page
REQUEST_TIMEOUT_SECONDS = 15
# Free tier is roughly 10 requests/minute; 6.5s keeps us under that with
# some margin instead of just re-testing the limit on every call.
REQUEST_DELAY_SECONDS = 6.5
RATE_LIMIT_BACKOFF_SECONDS = 20  # extra wait before retrying a 429 specifically

# Substrings (checked case-insensitively) in latest_action_description that
# mean a bill has already concluded -- signed, dead, withdrawn, etc. -- and
# is therefore not "pending" for a policy-staff brief. Wording for the same
# outcome varies a lot by state (CA: "Chaptered by Secretary of State", UT:
# "Governor Signed", NY: "APPROVAL MEMO.76" / "ENACTING CLAUSE STRICKEN"),
# so this list is checked against observed action text from all three
# tracked states, not just one. "veto" alone catches "Vetoed", "Veto
# Override", and "Governor Line Item Veto" in one shot.
_TERMINAL_ACTION_KEYWORDS = (
    "chaptered",
    "veto",
    "died",
    "failed",
    "withdrawn",
    "indefinitely postponed",
    "enacted",
    "became law",
    "enacting clause stricken",
    "approval memo",
)


def _get_api_key() -> str:
    api_key = os.environ.get("OPENSTATES_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENSTATES_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return api_key


def _request_with_retry(url: str, params: dict, headers: dict) -> dict | None:
    """GET url once, retry once more on timeout/non-200, else give up.

    Returns the parsed JSON body, or None if both attempts failed.
    """
    for attempt in (1, 2):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return response.json()
            print(f"[fetch]   request failed (HTTP {response.status_code}), attempt {attempt}/2: {url}")
            if attempt == 1:
                backoff = RATE_LIMIT_BACKOFF_SECONDS if response.status_code == 429 else REQUEST_DELAY_SECONDS
                time.sleep(backoff)
        except requests.exceptions.RequestException as exc:
            print(f"[fetch]   request error, attempt {attempt}/2: {exc}")
            if attempt == 1:
                time.sleep(REQUEST_DELAY_SECONDS)
    return None


def _resolve_current_session(state: str, headers: dict) -> str | None:
    """Pick the state's current legislative session as of today.

    "Current" = the session with the latest start_date that has already
    started, preferring a non-special session on ties (specials often
    share a start_date with the regular session around them).
    """
    data = _request_with_retry(
        f"{BASE_URL}/jurisdictions/{state.lower()}",
        {"include": "legislative_sessions"},
        headers,
    )
    if not data:
        return None

    today = date.today().isoformat()
    started = [
        s for s in data.get("legislative_sessions", [])
        if s.get("start_date") and s["start_date"] <= today
    ]
    if not started:
        return None

    started.sort(
        key=lambda s: (s["start_date"], s.get("classification") != "special", s.get("end_date", "")),
        reverse=True,
    )
    return started[0]["identifier"]


def _is_pending(raw_bill: dict) -> bool:
    """True unless the bill's latest action indicates it has concluded."""
    description = (raw_bill.get("latest_action_description") or "").lower()
    if any(keyword in description for keyword in _TERMINAL_ACTION_KEYWORDS):
        return False
    if "governor" in description and "sign" in description:
        return False  # catches "Governor Signed", "Signed by Governor", etc.
    return True


def _to_bill_record(state: str, session: str, raw_bill: dict) -> dict:
    abstracts = raw_bill.get("abstracts") or []
    text = abstracts[0].get("abstract", "").strip() if abstracts else ""
    text_available = bool(text)

    sources = raw_bill.get("sources") or []
    source_url = sources[0]["url"] if sources else raw_bill.get("openstates_url")

    return {
        "state": state.upper(),
        "bill_id": raw_bill.get("identifier"),
        "title": raw_bill.get("title"),
        "latest_action": raw_bill.get("latest_action_description"),
        "session": session,
        "source_url": source_url,
        "text": text if text_available else None,
        "text_available": text_available,
    }


def fetch_bills_for_state(state: str, session_scope: str = "current") -> list[dict]:
    """Fetch pending, AI-related bills for one state legislature.

    Inputs:
        state: Two-letter state code as used in config.yaml (e.g. "CA", "NY", "UT").
        session_scope: Which session to query. "current" resolves to that
            state's active session via the Open States API at call time.
            Any other value is treated as a literal Open States session
            identifier (e.g. "20252026").

    Output:
        A list of bill record dicts, each with: state, bill_id, title,
        latest_action, session, source_url, text (the bill abstract, or
        None if not yet available), and text_available (bool). Only bills
        whose latest action does not look terminal (signed/dead/withdrawn)
        are included -- see _is_pending.

    Failure behavior:
        - Each HTTP call is retried once on timeout or non-200; if both
          attempts fail, we log a message and return whatever bills were
          already collected for this state rather than crashing.
        - A state with zero matching bills logs "no AI bills found for
          {state}" and returns an empty list, not None and not an exception.
        - Requires OPENSTATES_API_KEY to be set in the environment (see
          .env.example); a missing key raises before any network call.
    """
    headers = {"X-API-KEY": _get_api_key()}

    if session_scope == "current":
        session = _resolve_current_session(state, headers)
        if session is None:
            print(f"[fetch]   could not resolve current session for {state}; skipping")
            return []
    else:
        session = session_scope

    time.sleep(REQUEST_DELAY_SECONDS)

    bills = []
    page = 1
    while True:
        params = {
            "jurisdiction": state.lower(),
            "session": session,
            "q": SEARCH_QUERY,
            "include": ["abstracts", "sources"],
            "page": page,
            "per_page": PER_PAGE,
        }
        data = _request_with_retry(f"{BASE_URL}/bills", params, headers)
        if data is None:
            print(f"[fetch]   giving up on {state} after a failed retry; returning {len(bills)} bill(s) fetched so far")
            break

        for raw_bill in data.get("results", []):
            if _is_pending(raw_bill):
                bills.append(_to_bill_record(state, session, raw_bill))

        max_page = data.get("pagination", {}).get("max_page", page)
        if page >= max_page:
            break
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    if not bills:
        print(f"[fetch] no AI bills found for {state}")

    return bills
