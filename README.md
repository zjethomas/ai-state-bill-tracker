# AI State Bill Tracker

A small tool that watches three state legislatures (California, New York,
Utah) for pending AI-related bills, filters out bills that only mention AI
in passing, classifies each real hit into a short AI-policy taxonomy,
writes a one-paragraph summary and an "Arizona relevance" note for each,
and produces a weekly markdown brief — automatically, via GitHub Actions.

Built for policy staff who need a fast read on what AI legislation is
**moving right now** in other states, without reading every bill
themselves.

## What it does, step by step

1. **Fetch** — pull bills currently active (not yet dead, not yet signed)
   in CA/NY/UT that mention AI, using the [Open States](https://openstates.org/)
   API.
2. **Filter** — drop bills where AI is just an incidental mention (e.g. one
   line in a big budget bill), keeping only bills substantively about AI.
3. **Classify** — use the Anthropic API (Claude) to sort each remaining
   bill into one or more categories (see `config.yaml`), and flag anything
   Claude isn't confident about for a human to double-check.
4. **Brief** — render everything into a single markdown file in `output/`,
   organized by state and category, with a summary and an Arizona
   relevance note per bill.
5. **Automate** — a GitHub Action runs this weekly and commits the new
   brief straight into `output/`.

**Status: scaffolding only.** The pipeline's steps (`src/fetch.py`,
`src/relevance.py`, `src/classify.py`, `src/brief.py`) are stubs right now
— they define what each step takes in and returns, but don't yet do the
real work. See `NOTES.md` for the build log.

## Getting the API keys

You need two keys. Neither costs money to obtain (Anthropic usage is
billed per API call once you're using it for real).

### Open States API key

1. Go to https://v3.openstates.org/accounts/profile/ and sign in or create
   a free account.
2. Your API key is shown on that profile page.
3. Open States has a free tier with a request-per-day limit, which is
   enough for a weekly job over 3 states.

### Anthropic API key

1. Go to https://console.anthropic.com/settings/keys and sign in or create
   an account.
2. Click "Create Key" and copy it — you won't be able to see it again.
3. You'll need billing set up on the account for the key to make calls.

### Setting the keys locally

```bash
cp .env.example .env
```

Then open `.env` and paste your two keys in. `.env` is listed in
`.gitignore` — it will never be committed.

### Setting the keys for the GitHub Action

The weekly Action reads the keys from GitHub Actions secrets, not from
`.env` (`.env` never leaves your machine). In the repo on GitHub, go to
**Settings → Secrets and variables → Actions** and add two repository
secrets: `OPENSTATES_API_KEY` and `ANTHROPIC_API_KEY`.

## Running it

Install dependencies (Python 3.10+):

```bash
pip install -r requirements.txt
```

Run the full pipeline:

```bash
python -m src.main
```

This prints progress for each stage (fetch → relevance → classify →
brief) and, once the stubs are filled in, writes a new file to
`output/YYYY-MM-DD-brief.md`.

Right now, since the pipeline steps are stubs, running this will get partway
through and raise `NotImplementedError` — that's expected until the real
logic is filled in.

## Reading a brief

Each weekly brief in `output/` is a plain markdown file, organized like:

- One section per state (CA, NY, UT).
- Within each state, bills grouped by taxonomy category (e.g. "Deepfakes &
  Synthetic Media").
- Each bill entry has: title, a short plain-language summary, its current
  status/last action, and an "Arizona relevance" note — why this bill
  might matter for Arizona specifically.
- A separate "needs human review" section at the bottom lists any bill
  Claude classified with low confidence — worth a quick manual read since
  the automated categorization isn't certain.

## Configuration

Edit `config.yaml` to change which states are tracked, the category
taxonomy, or the confidence threshold below which a bill gets flagged for
human review. No code changes needed for those adjustments.

## Project layout

```
config.yaml              user-editable settings (states, categories, threshold)
.env.example              placeholders for the two API keys — copy to .env
src/
  fetch.py                 pull candidate bills from Open States
  relevance.py              drop bills that only mention AI in passing
  classify.py               tag each bill with taxonomy categories via Claude
  brief.py                  render classified bills into a markdown brief
  main.py                   runs the four steps in order
output/                    weekly briefs land here
.github/workflows/weekly.yml   scheduled Action (schedule currently disabled)
tests/                     planned test cases (TEST_PLAN.md); no tests yet
NOTES.md                  running build log
```
