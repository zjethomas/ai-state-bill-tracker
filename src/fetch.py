"""Fetch pending AI-related bills from the Open States v3 API.

STUB — no logic implemented yet.
"""


def fetch_bills_for_state(state: str, session_scope: str = "current") -> list[dict]:
    """Fetch pending, AI-related bills for one state legislature.

    Inputs:
        state: Two-letter state code as used in config.yaml (e.g. "CA", "NY", "UT").
        session_scope: Which session to query. "current" resolves to that
            state's active session via the Open States API at call time.

    Output:
        A list of raw bill records (dicts) as returned by Open States v3,
        filtered server-side (via query params) to bills whose text or
        subject plausibly mentions AI. This is a coarse pre-filter only —
        src/relevance.py does the real "is this actually about AI" gate.
        Each dict is expected to carry at least: bill id, title, session,
        current status/actions, and a link to full text if available.

    Failure behavior:
        - Network/API errors (timeout, 4xx/5xx from Open States) should be
          raised, not swallowed, so src/main.py can report the failing
          state and continue with the others.
        - A state with zero matching bills returns an empty list, not None
          and not an exception.
        - Requires OPENSTATES_API_KEY to be set in the environment (see
          .env.example); missing key should raise a clear error before
          any network call is made.
    """
    raise NotImplementedError("fetch_bills_for_state is not yet implemented")
