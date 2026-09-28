# Media monitor

Track how much news coverage an organisation or topic gets, per country, and
whether it moves after your public actions (protests, report launches, open
letters).

It has three steps:

1. `fetch` counts matching articles per country per day and saves the article
   list (headline, outlet, date, link). Source: [GDELT](https://www.gdeltproject.org/),
   which is free and needs no key.
2. `classify` (optional) asks Claude to label each article: is it really about
   the topic, what is its stance (supportive / neutral / critical / mixed),
   what kind of journalism is it (investigative, own reporting, interview,
   opinion, wire rewrite, low-quality filler), and how deep is the coverage (1–5).
3. `report` writes `report.html` plus `weekly_counts.csv` and `articles.csv`.

The report shows per country: article counts, last 30 days vs the 30 days
before, a reach-weighted score based on outlet tiers, weekly bar charts with
your actions marked, a before/after table for each action, and the latest
articles with their labels.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .            # add '.[llm]' for the Claude labelling step
cp config.example.toml config.toml   # edit terms, countries, actions
mediamonitor fetch --days 30
mediamonitor report
open reports/report.html
```

Optional labelling (needs `ANTHROPIC_API_KEY`):

```bash
mediamonitor classify --limit 50   # try a small batch first, then check the labels
mediamonitor report
```

To build a history beyond GDELT's window, run `mediamonitor fetch --days 14`
once a week (cron, GitHub Actions, etc.). Re-running is safe: counts are
updated and articles are not duplicated.

## Configuration

See `config.example.toml`. The main parts:

- `[topic]`: a name, a one-paragraph description (used only by the labeller)
  and search terms. Add terms in local languages, since GDELT matches the
  original text.
- `[[countries]]`: one block per country. `gdelt` is the country's English
  name in lower case with spaces removed (`unitedkingdom`).
- `[[actions]]`: dated things you did. They appear as dashed lines on the charts.
- `[reach]`: a CSV of outlets with a tier (1 = large national, 2 = regional or
  trade, 3 = small) and a weight per tier. `outlets.example.csv` has a starter
  list of big outlets in NL, BE, DE, UK and US. Extend it for your countries.

## Limits you should know about

- **GDELT only searches about the last 3 months.** Older data needs regular
  fetching (above) or GDELT's BigQuery tables.
- **GDELT coverage is uneven.** It covers online news only (no TV, radio,
  print-only or paywalled-only content), and some countries and small outlets
  are thinly covered. Its crawler also changes over time. Compare trends
  within a country more than levels between countries.
- **Country = where the outlet is based**, not what the article is about.
- **Keyword matches include noise.** A short or common term can match unrelated
  articles. The labeller's `relevant` flag helps; tight search terms help more.
- **An article list request returns at most 250 articles.** The tool asks in
  7-day windows and warns if a window hits the cap; then use `--window 2` or less.
  The daily counts are not affected by this cap.
- **Reach is a rough proxy.** Tiers are hand-set. Real audience numbers
  (e.g. from national audience surveys or Similarweb) could replace them.
- **Labels are a model's judgement**, from the headline plus the opening text
  when the page can be downloaded (paywalls often block it). Check a sample by
  hand before trusting the percentages. The default model is `claude-opus-5`.
  You can set a cheaper one in `[classify] model`; check label quality if you do.
- **Before/after is not proof of effect.** Other news, weekends and slow news
  days all move the numbers. With many actions you could build a proper
  comparison (e.g. against other countries or a matched control topic).

## Ideas for next steps

- Other sources: [Media Cloud](https://www.mediacloud.org/) (free account,
  curated per-country outlet collections, good for research-grade counts),
  Event Registry / NewsAPI.ai (paid, has sentiment and outlet ranking).
- Share of voice: track a comparison topic (e.g. other AI-policy groups) with
  the same setup and show coverage side by side.
- Social media: Bluesky has an open API; X and TikTok are much harder.
- Batch the labelling with the Message Batches API to halve the cost.

## Development

```bash
pip install -e '.[llm,dev]'
pytest
```

The tests use saved GDELT-style responses in `tests/fixtures/` and a fake
Claude client, so they run offline.
