"""Filter out bills that only mention AI in passing.

Open States keyword/subject searches for "artificial intelligence" catch a
lot of noise: budget bills with an AI line item buried in an appropriations
table, omnibus tech bills that mention AI once in a definitions section,
etc. This module is the gate that keeps only bills where AI is a
substantive subject of the bill, not an incidental mention.

Rule (deliberately simple and strict -- when in doubt, drop):
  1. If the title mentions AI or a clearly AI-specific concept -> KEEP.
     A bill's own title is the strongest signal of what it's actually about.
  2. Else, if the text mentions a clearly AI-specific concept (automated
     decision systems, algorithmic discrimination, generative AI/foundation
     models, deepfakes/synthetic media, chatbots, agentic AI, machine
     learning) -> KEEP. These concepts aren't things a bill brings up in
     passing -- a bill doesn't say "algorithmic discrimination" or
     "deepfake" unless it's actually addressing that.
  3. Else, if the generic terms "AI" / "artificial intelligence" appear in
     the text -> KEEP if the text is short (roughly one or two sentences --
     the whole abstract is about that one thing) OR appears 2+ times in a
     longer text (a recurring subject, not a single incidental clause).
     A single mention in a long text reads as incidental -- the classic
     case is an omnibus budget bill that funds dozens of unrelated
     programs and happens to mention AI once.
  4. Otherwise -> DROP.

Concept patterns use proximity (e.g. "automated" near "decision") rather
than rigid exact phrases, because real bill titles paraphrase a lot:
"automated lending decision-making tools", "automated employment decision
tools", and "automated decision system" are all the same concept but no
single fixed string catches them all. See NOTES.md for known gaps this
still misses (e.g. "fabricated ... record" as a deepfake euphemism with no
"synthetic"/"deepfake" wording at all).

Separate from the AI rules above, a bill can also pass via the
"data_centers" taxonomy category (config.yaml) even with zero AI content:
bills that ban, newly regulate, or impose a moratorium on the CONSTRUCTION
of data centers over 50MW -- a live state policy fight distinct from AI
regulation, but Arizona-relevant given data center growth in-state. This
is deliberately narrow: a bill that merely mentions "data center" (a
cybersecurity bill, a tax-incentive bill that lists data centers as a
covered industry, a general power-cost bill) does NOT qualify. See
_judge_data_center_relevance.
"""

import re

# An abstract this short is essentially "what the bill does" in one or two
# sentences -- if AI shows up at all, it's almost certainly the subject,
# not an incidental aside. Longer text needs a stronger signal (see rule 3
# above), because that's exactly the shape of a false positive we're
# guarding against: a big omnibus bill that mentions AI once in passing.
_SHORT_TEXT_CHAR_THRESHOLD = 300

_GENERAL_AI_PATTERNS = [
    re.compile(r"\bartificial intelligence\b", re.IGNORECASE),
    # Deliberately case-sensitive: bare lowercase "ai" is not a reliable
    # signal (word-boundary regex still catches "AI-powered", "(AI)", etc).
    re.compile(r"\bAI\b"),
    re.compile(r"\bA\.I\.\b"),
]

_SPECIFIC_AI_CONCEPT_PATTERNS = [
    # Proximity match: "automated"/"automatic" ... "decision" within a
    # short span, catching "automated decision system", "automated
    # decision-making", "automated lending decision-making tools",
    # "automated employment decision tools", etc.
    re.compile(r"\bautomat(ed|ic)\b.{0,40}\bdecisions?\b", re.IGNORECASE),
    re.compile(r"\balgorithmic discrimination\b", re.IGNORECASE),
    re.compile(r"\balgorithmic bias\b", re.IGNORECASE),
    re.compile(r"\bgenerative (artificial intelligence|AI)\b", re.IGNORECASE),
    re.compile(r"\bfoundation models?\b", re.IGNORECASE),
    re.compile(r"\blarge language models?\b", re.IGNORECASE),
    re.compile(r"\bmachine learning\b", re.IGNORECASE),
    # "deepfake", "deep-fake", and "deep fake" all show up in real bill text.
    re.compile(r"\bdeep[- ]?fakes?\b", re.IGNORECASE),
    # Proximity match for "synthetic content/media/performer/voice/...",
    # since "synthetic content creation system" and "synthetic media" are
    # the same underlying policy topic but not the same literal phrase.
    re.compile(r"\bsynthetic\b.{0,30}\b(content|media|performers?|voices?|actors?|images?|videos?)\b", re.IGNORECASE),
    re.compile(r"\bchatbots?\b", re.IGNORECASE),
    re.compile(r"\bcompanion (chatbot|AI)\b", re.IGNORECASE),
    re.compile(r"\bagentic (artificial intelligence|AI)\b", re.IGNORECASE),
    re.compile(r"\bAI agents?\b"),
]

_DATA_CENTER_TERM_PATTERN = re.compile(r"\bdata centers?\b", re.IGNORECASE)

# "50 MW", "50MW", "50-megawatt", "50 megawatts", etc.
_DATA_CENTER_SIZE_THRESHOLD_PATTERN = re.compile(r"\b\d[\d,]*\s*-?\s*(mw|megawatts?)\b", re.IGNORECASE)

# "data center" near a construction/siting/build word, in either order.
_DATA_CENTER_CONSTRUCTION_PATTERN = re.compile(
    r"\bdata centers?\b.{0,60}\b(construct\w*|sit(e|ing)|build\w*|development)\b"
    r"|\b(construct\w*|sit(e|ing)|build\w*|development)\b.{0,60}\bdata centers?\b",
    re.IGNORECASE,
)

_DATA_CENTER_RESTRICTION_PATTERN = re.compile(
    r"\b(moratoriums?|bans?|prohibit\w*|restrict\w*)\b", re.IGNORECASE
)


def _has_match(patterns: list, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _count_matches(patterns: list, text: str) -> int:
    return sum(len(p.findall(text)) for p in patterns)


def _judge_data_center_relevance(bill: dict) -> tuple[bool, str]:
    """Check the narrow "data_centers" category: construction bans/moratoriums/
    regulation for data centers over 50MW -- see module docstring.

    Requires "data center(s)" AND an explicit MW/megawatt size threshold
    (the "over 50MW" part of the category definition is mandatory, not
    just a nice-to-have signal) AND either construction/siting language
    near "data center" or a ban/moratorium/restriction word. A moratorium
    or ban on data centers with no stated size threshold does NOT qualify
    -- it may well be about smaller facilities too, which is out of scope.
    """
    combined = f"{bill.get('title') or ''} {bill.get('text') or ''}"
    if not _DATA_CENTER_TERM_PATTERN.search(combined):
        return False, ""
    if not _DATA_CENTER_SIZE_THRESHOLD_PATTERN.search(combined):
        return False, ""

    if _DATA_CENTER_CONSTRUCTION_PATTERN.search(combined):
        return True, "passed: data center construction/siting tied to a MW size threshold"
    if _DATA_CENTER_RESTRICTION_PATTERN.search(combined):
        return True, "passed: data center construction moratorium/ban/restriction, MW size threshold stated"

    return False, ""


def judge_relevance(bill: dict) -> tuple[bool, str]:
    """Decide whether a single bill is substantively about AI, and why.

    Also passes bills that don't mention AI at all but clearly meet the
    narrow "data_centers" category (construction ban/moratorium/regulation
    for data centers over 50MW) -- see _judge_data_center_relevance and the
    module docstring. That path is checked only as a fallback, after the
    AI-based rules find nothing, and gets its own "passed: data center..."
    reason so it's auditable separately from AI-keyword passes.

    Input:
        bill: A bill record from src/fetch.py, with at least "title" and
            "text" (the abstract, or None/empty if not yet available).

    Output:
        (passed, reason) -- passed is True if AI is a substantive subject
        of the bill, or it clearly meets the data_centers category; reason
        is a short human-readable phrase explaining the decision either
        way, for audit logging.

    Failure behavior:
        Raises ValueError if the bill has neither a title nor text --
        that's malformed input from fetch.py, not a judgment call.
    """
    title = bill.get("title") or ""
    text = bill.get("text") or ""
    if not title and not text:
        raise ValueError(f"bill {bill.get('bill_id', '?')} has neither title nor text")

    if _has_match(_GENERAL_AI_PATTERNS, title) or _has_match(_SPECIFIC_AI_CONCEPT_PATTERNS, title):
        return True, "AI term in title"

    if _has_match(_SPECIFIC_AI_CONCEPT_PATTERNS, text):
        return True, "AI-specific concept in text"

    general_hits = _count_matches(_GENERAL_AI_PATTERNS, text)
    if general_hits >= 2:
        return True, f"'AI'/'artificial intelligence' mentioned {general_hits}x in text"

    if general_hits == 1 and len(text) <= _SHORT_TEXT_CHAR_THRESHOLD:
        return True, "AI mentioned in a short, focused abstract"

    data_center_passed, data_center_reason = _judge_data_center_relevance(bill)
    if data_center_passed:
        return True, data_center_reason

    if not text:
        return False, "no AI term in title, and no bill text available yet"

    if general_hits == 1:
        return False, "AI mentioned only once in a long text -- likely a passing reference"

    return False, "no AI-related term found in title or text"


def filter_relevant_bills(bills: list[dict]) -> list[dict]:
    """Apply the relevance gate to a full list of bills and report the results.

    Input:
        bills: Bill records from src/fetch.py, each expected to carry a
            "state" field (used to group the audit output).

    Output:
        The subset of bills that passed judge_relevance, each with an
        added "relevance_reason" key recording why it was kept. Dropped
        bills are not returned, but are never silently discarded -- see
        side effects below.

    Side effects:
        Prints, per state: a before -> after count, and the title + reason
        for every dropped bill, so a human can eyeball whether the gate is
        too strict or too loose before trusting it.

    Failure behavior:
        Propagates ValueError from judge_relevance on malformed input
        (missing title and text) rather than skipping the bill silently.
    """
    kept = []
    total_by_state: dict[str, int] = {}
    kept_by_state: dict[str, int] = {}
    dropped_by_state: dict[str, list[tuple[str, str]]] = {}

    for bill in bills:
        state = bill.get("state", "?")
        total_by_state[state] = total_by_state.get(state, 0) + 1

        passed, reason = judge_relevance(bill)
        if passed:
            kept.append({**bill, "relevance_reason": reason})
            kept_by_state[state] = kept_by_state.get(state, 0) + 1
        else:
            title = bill.get("title") or "(no title)"
            dropped_by_state.setdefault(state, []).append((title, reason))

    print("[relevance] before -> after, per state:")
    for state, total in total_by_state.items():
        after = kept_by_state.get(state, 0)
        print(f"[relevance]   {state}: {total} -> {after}")

    for state, dropped in dropped_by_state.items():
        print(f"[relevance] dropped in {state} ({len(dropped)}):")
        for title, reason in dropped:
            print(f"[relevance]   - {title}  [{reason}]")

    return kept
