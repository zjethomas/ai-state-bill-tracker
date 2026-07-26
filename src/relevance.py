"""Filter out bills that only mention AI in passing.

STUB — no logic implemented yet.

Open States keyword/subject searches for "artificial intelligence" catch a
lot of noise: budget bills with an AI line item buried in an appropriations
table, omnibus tech bills that mention AI once in a definitions section,
etc. This module is the gate that keeps only bills where AI is a
substantive subject of the bill, not an incidental mention.
"""


def is_substantively_about_ai(bill: dict) -> bool:
    """Decide whether a bill is substantively about AI, not just mentioning it.

    Input:
        bill: A raw bill record as returned by src/fetch.py
            (fetch_bills_for_state), containing at minimum title and
            available bill text/summary.

    Output:
        True if AI appears to be a central subject of the bill (e.g. the
        bill regulates, funds, or defines requirements for AI systems).
        False if AI is mentioned only in passing (e.g. a single
        definitions-section reference, or an unrelated bill that lists
        "artificial intelligence" among many funded technology categories).

    Failure behavior:
        - If bill text is unavailable (bill has no full text posted yet),
          fall back to title/summary-only judgment and note the reduced
          confidence rather than raising — pending bills often lack posted
          text early in session, and that's expected, not an error.
        - Should not raise on well-formed input; malformed input (missing
          both title and text) should raise ValueError so the caller can
          skip the bill loudly instead of silently misclassifying it.
    """
    raise NotImplementedError("is_substantively_about_ai is not yet implemented")
