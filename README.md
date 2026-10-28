# icebreaker-bulk

Scripts for generating personalized opening lines ("icebreakers") for cold
outreach at scale, plus enrichment helpers for the source lead data.

- `scripts/icebreakers_bulk.py` / `icebreakers_search.py` / `icebreakers_from_description.py` — generate icebreakers from company descriptions or search results
- `scripts/enrich_apify.py` / `enrich_apify_v2.py` — enrich rows through an Apify actor
- `scripts/add_short_columns.py` — helper for the spreadsheet layout
- `madaar/` — KSA-specific company enrichment

Requires a Serper and an Apify token in `.env` (see `.env.example`). Generated
sheets, raw lead files and per-prospect icebreakers are not published.
