"""Turn the database into a self-contained HTML report plus CSV files."""

from __future__ import annotations

import csv
import html
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .reach import ReachTable
from .store import Store

GOOD_CATEGORIES = {"investigative", "original_reporting", "interview_feature"}
WEAK_CATEGORIES = {"wire_rewrite", "low_quality"}


# ---------- calculations (kept separate from HTML so they are easy to test) ----------

def daily_series(rows, countries: list[str]) -> tuple[list[date], dict[str, list[int]]]:
    """Return a continuous list of days and, per country, a count per day (0 if missing)."""
    by_country: dict[str, dict[date, int]] = defaultdict(dict)
    for r in rows:
        by_country[r["country"]][date.fromisoformat(r["day"])] = r["count"]
    all_days = [d for c in by_country.values() for d in c]
    if not all_days:
        return [], {c: [] for c in countries}
    start, end = min(all_days), max(all_days)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return days, {c: [by_country[c].get(d, 0) for d in days] for c in countries}


def weekly(days: list[date], values: list[int]) -> list[tuple[date, int]]:
    """Sum daily values into weeks starting on Monday."""
    weeks: dict[date, int] = {}
    for d, v in zip(days, values):
        monday = d - timedelta(days=d.weekday())
        weeks[monday] = weeks.get(monday, 0) + v
    return sorted(weeks.items())


def window_mean(days: list[date], values: list[int], start: date, end: date) -> float | None:
    """Mean daily value for start <= day < end, or None if the window is not fully covered."""
    if not days or start < days[0] or end - timedelta(days=1) > days[-1]:
        return None
    picked = [v for d, v in zip(days, values) if start <= d < end]
    return sum(picked) / len(picked) if picked else None


def before_after(days, values, action_day: date, window: int = 7) -> tuple[float | None, float | None]:
    """Mean articles per day in the `window` days before the action vs. from the action day on."""
    before = window_mean(days, values, action_day - timedelta(days=window), action_day)
    after = window_mean(days, values, action_day, action_day + timedelta(days=window))
    return before, after


def country_summaries(cfg: Config, days, series, articles, reach: ReachTable) -> list[dict]:
    out = []
    today = days[-1] if days else date.today()
    for c in cfg.countries:
        vals = series.get(c.code, [])
        last30 = window_mean(days, vals, today - timedelta(days=29), today + timedelta(days=1))
        prev30 = window_mean(days, vals, today - timedelta(days=59), today - timedelta(days=29))
        arts = [a for a in articles if a["country"] == c.code]
        classified = [a for a in arts if a["relevant"] is not None]
        relevant = [a for a in classified if a["relevant"]]
        # Articles we know are irrelevant do not count toward reach.
        counted = [a for a in arts if a["relevant"] is None or a["relevant"]]
        stance = Counter(a["stance"] for a in relevant)
        category = Counter(a["category"] for a in relevant)
        out.append({
            "code": c.code,
            "name": c.name,
            "total": sum(vals),
            "per_day_last30": last30,
            "per_day_prev30": prev30,
            "stored": len(arts),
            "weighted_reach": sum(reach.weight(a["domain"]) for a in counted),
            "classified": len(classified),
            "relevant": len(relevant),
            "stance": stance,
            "good_share": (sum(category[k] for k in GOOD_CATEGORIES) / len(relevant)) if relevant else None,
            "weak_share": (sum(category[k] for k in WEAK_CATEGORIES) / len(relevant)) if relevant else None,
        })
    return out


# ---------- HTML ----------

CSS = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f3f2ef; --border: #e2e1dc;
  --text: #0b0b0b; --text-2: #52514e; --muted: #7a7974;
  --series-1: #2a78d6; --marker: #eb6834;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #242423; --border: #3a3a38;
    --text: #ffffff; --text-2: #c3c2b7; --muted: #95948c;
    --series-1: #3987e5; --marker: #d95926;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #242423; --border: #3a3a38;
  --text: #ffffff; --text-2: #c3c2b7; --muted: #95948c;
  --series-1: #3987e5; --marker: #d95926;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 40px 0 8px; }
p.sub, .note { color: var(--text-2); margin: 0 0 12px; }
.note { font-size: 13px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--text-2); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.table-wrap table { min-width: 720px; }
td:first-child { white-space: nowrap; }
a { color: var(--series-1); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.card { background: var(--surface-2); border-radius: 8px; padding: 12px; }
.card h3 { font-size: 15px; margin: 0 0 4px; }
.card svg { width: 100%; height: auto; display: block; }
.axis { fill: var(--muted); font-size: 10px; }
.bar { fill: var(--series-1); }
.bar:hover { opacity: .75; }
.action-line { stroke: var(--marker); stroke-width: 1.5; stroke-dasharray: 3 3; }
.baseline { stroke: var(--border); }
.legend { font-size: 13px; color: var(--text-2); margin: 4px 0 12px; }
.legend .swatch { display: inline-block; width: 14px; height: 0; border-top: 2px dashed var(--marker);
  vertical-align: middle; margin-right: 6px; }
"""


def _fmt(x, digits=1, pct=False):
    if x is None:
        return "–"
    if pct:
        return f"{x * 100:.0f}%"
    return f"{x:,.{digits}f}"


def _bar_chart(weeks: list[tuple[date, int]], actions, width=320, height=120) -> str:
    """Weekly bars for one country, with dashed lines on action dates."""
    if not weeks:
        return '<p class="note">No data yet.</p>'
    pad_l, pad_b, pad_t = 28, 18, 8
    plot_w, plot_h = width - pad_l - 4, height - pad_b - pad_t
    top = max(v for _, v in weeks) or 1
    n = len(weeks)
    step = plot_w / n
    bar_w = max(step - 2, 1)  # 2px gap between bars
    first, last = weeks[0][0], weeks[-1][0] + timedelta(days=7)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    parts.append(f'<text class="axis" x="{pad_l - 4}" y="{pad_t + 8}" text-anchor="end">{top}</text>')
    parts.append(f'<text class="axis" x="{pad_l - 4}" y="{pad_t + plot_h}" text-anchor="end">0</text>')
    for i, (wk, v) in enumerate(weeks):
        h = plot_h * v / top
        x = pad_l + i * step
        y = pad_t + plot_h - h
        # Transparent full-height rect gives a bigger hover target than the bar.
        parts.append(
            f'<g><title>Week of {wk.isoformat()}: {v} articles</title>'
            f'<rect x="{x:.1f}" y="{pad_t}" width="{step:.1f}" height="{plot_h}" fill="transparent"/>'
            f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="{min(2, bar_w / 2):.1f}"/></g>'
        )
    base_y = pad_t + plot_h
    parts.append(f'<line class="baseline" x1="{pad_l}" x2="{pad_l + plot_w}" y1="{base_y}" y2="{base_y}"/>')
    for a in actions:
        if first <= a.date < last:
            x = pad_l + plot_w * (a.date - first).days / (last - first).days
            parts.append(
                f'<g><title>{html.escape(a.date.isoformat() + ": " + a.label)}</title>'
                f'<line class="action-line" x1="{x:.1f}" x2="{x:.1f}" y1="{pad_t}" y2="{base_y}"/></g>'
            )
    parts.append(f'<text class="axis" x="{pad_l}" y="{height - 4}">{first.strftime("%d %b %Y")}</text>')
    parts.append(f'<text class="axis" x="{pad_l + plot_w}" y="{height - 4}" text-anchor="end">'
                 f'{(last - timedelta(days=1)).strftime("%d %b %Y")}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_html(cfg: Config, days, series, summaries, articles, reach: ReachTable,
                generated: datetime, max_articles: int = 150) -> str:
    e = html.escape
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{e(cfg.name)} media monitor</title><style>{CSS}</style></head><body><main>",
        f"<h1>Media attention: {e(cfg.name)}</h1>",
    ]
    span = f"{days[0].isoformat()} to {days[-1].isoformat()}" if days else "no data"
    out.append(f"<p class='sub'>Source: GDELT. Period: {span}. Generated {generated:%Y-%m-%d %H:%M} UTC.</p>")

    any_classified = any(s["classified"] for s in summaries)
    out.append("<h2>Per country</h2><div class='table-wrap'><table><thead><tr>"
               "<th>Country</th><th class='num'>Articles (GDELT count)</th>"
               "<th class='num'>Per day, last 30 days</th><th class='num'>Per day, 30 days before</th>"
               "<th class='num'>Reach-weighted</th>")
    if any_classified:
        out.append("<th class='num'>Relevant / labelled</th><th>Stance (relevant only)</th>"
                   "<th class='num'>Original work</th><th class='num'>Rewrite / low quality</th>")
    out.append("</tr></thead><tbody>")
    for s in summaries:
        out.append(f"<tr><td>{e(s['name'])}</td><td class='num'>{s['total']:,}</td>"
                   f"<td class='num'>{_fmt(s['per_day_last30'])}</td><td class='num'>{_fmt(s['per_day_prev30'])}</td>"
                   f"<td class='num'>{_fmt(s['weighted_reach'], 0)}</td>")
        if any_classified:
            st = s["stance"]
            stance_txt = ", ".join(f"{k} {st[k]}" for k in ("supportive", "neutral", "mixed", "critical") if st[k]) or "–"
            out.append(f"<td class='num'>{s['relevant']} / {s['classified']}</td><td>{e(stance_txt)}</td>"
                       f"<td class='num'>{_fmt(s['good_share'], pct=True)}</td>"
                       f"<td class='num'>{_fmt(s['weak_share'], pct=True)}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    out.append("<p class='note'>Articles = GDELT's matched-article count. Reach-weighted = stored articles "
               "weighted by outlet tier (see outlets CSV); articles labelled irrelevant are left out. "
               "Original work = investigative, own reporting, interviews and features.</p>")

    out.append("<h2>Articles per week</h2>")
    if cfg.actions:
        out.append("<p class='legend'><span class='swatch'></span>Your actions (hover for the label)</p>")
    out.append("<p class='note'>Each chart has its own vertical scale, so compare shapes, not heights.</p>")
    out.append("<div class='grid'>")
    for c in cfg.countries:
        wk = weekly(days, series.get(c.code, []))
        out.append(f"<div class='card'><h3>{e(c.name)}</h3>{_bar_chart(wk, cfg.actions)}</div>")
    out.append("</div>")

    if cfg.actions and days:
        out.append("<h2>Before and after your actions</h2>")
        out.append("<p class='note'>Mean articles per day in the 7 days before each action vs. the 7 days "
                   "starting on the action day. This is a rough signal, not proof of effect: other news, "
                   "weekends and GDELT's own coverage also move these numbers.</p>")
        out.append("<div class='table-wrap'><table><thead><tr><th>Date</th><th>Action</th>")
        out += [f"<th class='num'>{e(c.code)}</th>" for c in cfg.countries]
        out.append("</tr></thead><tbody>")
        for a in cfg.actions:
            out.append(f"<tr><td>{a.date.isoformat()}</td><td>{e(a.label)}</td>")
            for c in cfg.countries:
                b, af = before_after(days, series.get(c.code, []), a.date)
                cell = "–" if b is None or af is None else f"{b:.1f} → {af:.1f}"
                out.append(f"<td class='num'>{cell}</td>")
            out.append("</tr>")
        out.append("</tbody></table></div>")

    out.append(f"<h2>Latest articles</h2><p class='note'>Newest {min(max_articles, len(articles))} "
               f"of {len(articles)} stored.</p>")
    out.append("<div class='table-wrap'><table><thead><tr><th>Date</th><th>Country</th><th>Outlet</th>"
               "<th class='num'>Tier</th><th>Headline</th>")
    if any_classified:
        out.append("<th>Stance</th><th>Type</th><th class='num'>Depth</th>")
    out.append("</tr></thead><tbody>")
    for a in articles[:max_articles]:
        tier = reach.tier(a["domain"])
        out.append(f"<tr><td>{a['seen_at'][:10]}</td><td>{e(a['country'])}</td><td>{e(a['domain'])}</td>"
                   f"<td class='num'>{tier or '–'}</td>"
                   f"<td><a href='{e(a['url'])}' rel='noopener noreferrer'>{e(a['title'] or a['url'])}</a></td>")
        if any_classified:
            if a["relevant"] is None:
                out.append("<td>–</td><td>–</td><td class='num'>–</td>")
            elif not a["relevant"]:
                out.append(f"<td colspan='3' title='{e(a['rationale'] or '')}'>not relevant</td>")
            else:
                out.append(f"<td title='{e(a['rationale'] or '')}'>{e(a['stance'])}</td>"
                           f"<td>{e(a['category'])}</td><td class='num'>{a['depth']}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div></main></body></html>")
    return "".join(out)


def write_report(cfg: Config, store: Store, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    codes = [c.code for c in cfg.countries]
    days, series = daily_series(store.daily_counts(), codes)
    articles = [dict(r) for r in store.articles_with_labels()]
    reach = ReachTable.from_csv(cfg.outlets_file, cfg.tier_weights, cfg.unknown_weight)
    summaries = country_summaries(cfg, days, series, articles, reach)

    with (out_dir / "weekly_counts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["week_start", *codes])
        weekly_by_country = {c: dict(weekly(days, series[c])) for c in codes}
        for wk in sorted({wk for d in weekly_by_country.values() for wk in d}):
            w.writerow([wk.isoformat(), *[weekly_by_country[c].get(wk, 0) for c in codes]])

    with (out_dir / "articles.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["seen_at", "country", "domain", "tier", "weight", "language", "title", "url",
                  "relevant", "stance", "category", "depth", "rationale"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for a in articles:
            w.writerow({**{k: a.get(k) for k in fields},
                        "tier": reach.tier(a["domain"]), "weight": reach.weight(a["domain"])})

    page = render_html(cfg, days, series, summaries, articles, reach, datetime.now(timezone.utc))
    path = out_dir / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
