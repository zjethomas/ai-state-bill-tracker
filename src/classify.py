"""Classify a bill into the AI-policy taxonomy using the Anthropic API.

STUB — no logic implemented yet.
"""


def classify_bill(bill: dict, categories: list[dict]) -> dict:
    """Classify a bill into one or more taxonomy categories via Claude.

    Inputs:
        bill: A bill record that has already passed the relevance gate
            (src/relevance.py), containing at least title and available text.
        categories: The taxonomy from config.yaml's `categories` list, each
            entry shaped like {"id": ..., "label": ...}.

    Output:
        A dict shaped like:
            {
                "categories": [
                    {"id": "deepfakes_synthetic_media", "confidence": 0.85},
                    ...
                ],
                "needs_human_review": bool,
            }
        A bill may match more than one category. "needs_human_review" is
        True whenever every matched category's confidence falls below
        config.yaml's relevance_threshold, OR no category matches at all —
        low confidence means flag for a human to look at, not guess.

    Failure behavior:
        - API errors (timeout, rate limit, malformed response) should be
          raised, not silently defaulted to a category — a bill that fails
          to classify should surface as a failure in src/main.py, not get
          mislabeled.
        - Requires ANTHROPIC_API_KEY in the environment (see .env.example).
    """
    raise NotImplementedError("classify_bill is not yet implemented")
