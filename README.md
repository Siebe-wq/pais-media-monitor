# Media monitor

Track how much news coverage a topic gets, per country, and whether it moves
after your public actions (protests, report launches, open letters).

The example config tracks post-acute infection syndromes (PAIS): long COVID,
ME/CFS and similar illnesses that follow an infection. Any other topic works
by editing the config.

It has three steps:

1. `fetch` counts matching articles per country per day and saves the article
   list (headline, outlet, date, link). Source: [GDELT](https://www.gdeltproject.org/),
   which is free and needs no key.
2. `classify` (optional) asks Claude to label each article: is it really about
   the topic, what is its stance (supportive / neutral / critical / mixed, as
   defined in your config), what kind of journalism is it (investigative, own
   reporting, interview, opinion, wire rewrite, low-quality filler), how deep
   is the coverage (1–5), and optionally which condition it is mainly about.
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
mediamonitor terms                   # check each search term for noise
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
  and search terms. **Write terms in English.** GDELT machine-translates
  articles in about 65 languages into English and searches the translation, so
  "long covid" also finds Dutch and German articles. Avoid short, ambiguous
  terms: "PAIS" alone would match the Spanish and Portuguese word for "country".
- `[[countries]]`: one block per country. `gdelt` is the country's English
  name in lower case with spaces removed (`unitedkingdom`).
- `[[actions]]`: dated things you did. They appear as dashed lines on the charts.
- `[classify]`: the model, a `stance_guide` that says what "supportive" and
  "critical" mean for your topic, and optional `subtopics`.
- `[reach]`: a CSV of outlets with a tier (1 = large national, 2 = regional or
  trade, 3 = small) and a weight per tier. `outlets.example.csv` has a starter
  list of big outlets in NL, BE, DE, UK and US. Extend it for your countries.

## Limits you should know about

- **Article lists only cover the last 3 months.** Older articles need regular
  fetching (see the weekly run below). GDELT's daily counts reportedly go back
  to 2017, but the tool does not fetch that far back yet.
- **GDELT limits how often you can ask.** It allows about one request every
  5 seconds per internet address. Shared machines (cloud sandboxes, GitHub's
  runners) can be refused even when the tool is polite, because others share
  the address. The tool waits and retries, up to about 10 minutes per request.
- **GDELT coverage is uneven.** It covers online news only (no TV, radio,
  print-only or paywalled-only content), and some countries and small outlets
  are thinly covered. Its crawler also changes over time. Compare trends
  within a country more than levels between countries.
- **Country = where the outlet is based**, not what the article is about.
- **Keyword matches include noise.** A short or common term can match unrelated
  articles, and "post-covid" can match articles about the economy after the
  pandemic. Run `mediamonitor terms` and read the sample headlines. The
  labeller's `relevant` flag also helps.
- **Search goes through machine translation.** A term can be missed if the
  translation renders it differently (e.g. Dutch "ME/CVS" may or may not come
  out as "ME/CFS"). Check with `terms` and add variants if needed.
- **An article list request returns at most 250 articles.** The tool asks for
  the whole period first and halves it until each part fits, down to 6 hours.
  The daily counts are not affected by this cap.
- **Reach is a rough proxy.** Tiers are hand-set. Real audience numbers
  (e.g. from national audience surveys or Similarweb) could replace them.
- **Labels are a model's judgement**, from the headline plus the opening text
  when the page can be downloaded (paywalls often block it). Check a sample by
  hand before trusting the percentages. The default model is `claude-sonnet-5-5`.
- **Before/after is not proof of effect.** Other news, weekends and slow news
  days all move the numbers. With many actions you could build a proper
  comparison (e.g. against other countries or a matched control topic).

## Ideas for next steps

- Other sources: [Media Cloud](https://www.mediacloud.org/) (free account,
  curated per-country outlet collections, good for research-grade counts),
  Event Registry / NewsAPI.ai (paid, has sentiment and outlet ranking).
- Share of voice: track a comparison topic (e.g. another patient group's
  condition) with the same setup and show coverage side by side.
- Social media: Bluesky has an open API; X and TikTok are much harder.
- Batch the labelling with the Message Batches API to halve the cost.

## Automatic weekly run (GitHub Actions)

`.github/workflows/fetch.yml` runs on GitHub's machines every Monday. It:

1. fetches the last 14 days from GDELT, using `config.toml`;
2. labels up to 200 new articles with Claude, but only if the repository has
   an `ANTHROPIC_API_KEY` secret (Settings > Secrets and variables > Actions);
3. rebuilds the report into `docs/` (`docs/index.html`, plus CSV files);
4. saves the database (`data/mediamonitor.db`) and report back into the repo.

To run it by hand: the **Actions** tab > **Fetch media data** > **Run workflow**.
For a first run, set "days" to 90 to fill in the last three months.

To view the report as a web page instead of as source code, turn on GitHub
Pages once: Settings > Pages > Source "Deploy from a branch", pick this
branch and the `/docs` folder. Note that in a public repository, Pages and
the data files are public too.

## Running it in Claude Code on the web

The cloud sandbox blocks most outside hosts by default. To let it reach GDELT,
open the environment's settings (the environment menu in the session's title
bar, then Edit) and either add `api.gdeltproject.org` to the allowed domains
or choose a broader network access level. See
https://code.claude.com/docs/en/claude-code-on-the-web. For `classify` with
`fetch_article_text = true`, the sandbox also needs to reach the news sites
themselves, which in practice means full network access. The labeller also
needs an `ANTHROPIC_API_KEY` set as an environment secret.

## Development

```bash
pip install -e '.[llm,dev]'
pytest
```

The tests use saved GDELT-style responses in `tests/fixtures/` and a fake
Claude client, so they run offline.
