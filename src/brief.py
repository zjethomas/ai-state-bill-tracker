"""Render classified bills into a weekly markdown brief.

STUB — no logic implemented yet.
"""


def render_brief(classified_bills: list[dict], week_of: str) -> str:
    """Render classified, relevant bills into a markdown brief.

    Inputs:
        classified_bills: A list of dicts, each combining a bill record
            (src/fetch.py) with its classification (src/classify.py), e.g.
            {"bill": {...}, "classification": {...}, "summary": str,
             "arizona_relevance": str}.
        week_of: ISO date string (e.g. "2026-07-26") identifying the brief,
            used in the heading and as part of the output filename.

    Output:
        A single markdown string: a per-state, per-category breakdown of
        bills with title, a short summary, current status/last action, and
        an "Arizona relevance" note for each bill. Bills flagged
        needs_human_review should be called out in their own section so
        policy staff know which ones weren't confidently classified.
        Caller (src/main.py) is responsible for writing this string to
        output/YYYY-MM-DD-brief.md.

    Failure behavior:
        - An empty classified_bills list produces a valid brief that says
          no relevant AI bills were found that week, not an error.
        - Should not raise on well-formed input dicts; missing optional
          fields (e.g. no arizona_relevance yet) should render as "TBD"
          rather than crashing the whole brief.
    """
    raise NotImplementedError("render_brief is not yet implemented")
