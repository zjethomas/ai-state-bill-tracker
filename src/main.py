"""Orchestrate the pipeline: fetch -> relevance -> classify -> brief.

STUB — wires the steps together and prints progress so the pipeline stays
legible, but each step it calls is itself unimplemented (see fetch.py,
relevance.py, classify.py, brief.py). Running this script today will raise
NotImplementedError once it reaches the first real step.
"""

import datetime

import yaml

from src.brief import render_brief
from src.classify import classify_bill
from src.fetch import fetch_bills_for_state
from src.relevance import filter_relevant_bills


def load_config(path: str = "config.yaml") -> dict:
    """Load user-editable settings (states, categories, thresholds) from config.yaml.

    Input:
        path: Path to the YAML config file.

    Output:
        The parsed config as a dict, matching config.yaml's structure
        (states, session_scope, categories, relevance_threshold).

    Failure behavior:
        - Missing file or invalid YAML should raise — there's no sane
          default for "which states to track", so the pipeline must not
          silently run with an empty scope.
    """
    with open(path) as f:
        return yaml.safe_load(f)


def run() -> None:
    """Run the full weekly pipeline end to end.

    Steps, in order, with progress printed at each stage so a human
    watching CI logs (or a local run) can tell where things stand:
        1. fetch    — pull pending AI-related bills per state.
        2. relevance — drop bills that only mention AI in passing.
        3. classify — tag each surviving bill with taxonomy categories.
        4. brief    — render everything into a markdown file under output/.

    Failure behavior:
        - A single state failing to fetch should not abort the whole run;
          log it and continue with the remaining states (final brief notes
          which states, if any, failed).
        - Any other unhandled exception should propagate so GitHub Actions
          marks the run as failed rather than silently committing a partial
          or empty brief.
    """
    config = load_config()
    print(f"[main] loaded config: states={config['states']}")

    print("[main] step 1/4: fetch")
    all_bills = []
    for state in config["states"]:
        print(f"[main]   fetching {state} ({config['session_scope']} session)...")
        bills = fetch_bills_for_state(state, config["session_scope"])
        print(f"[main]   {state}: {len(bills)} candidate bill(s)")
        all_bills.extend(bills)

    print("[main] step 2/4: relevance filtering")
    relevant_bills = filter_relevant_bills(all_bills)
    print(f"[main]   {len(relevant_bills)}/{len(all_bills)} bills passed the relevance gate")

    print("[main] step 3/4: classification")
    classified_bills = []
    for bill in relevant_bills:
        classification = classify_bill(bill, config["categories"])
        classified_bills.append({"bill": bill, "classification": classification})
    print(f"[main]   classified {len(classified_bills)} bill(s)")

    print("[main] step 4/4: brief")
    week_of = datetime.date.today().isoformat()
    markdown = render_brief(classified_bills, week_of)
    output_path = f"output/{week_of}-brief.md"
    with open(output_path, "w") as f:
        f.write(markdown)
    print(f"[main]   wrote {output_path}")


if __name__ == "__main__":
    run()
