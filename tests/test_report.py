from datetime import date

from mediamonitor.config import load_config
from mediamonitor.gdelt import DayCount, parse_articles
from mediamonitor.report import before_after, daily_series, weekly, write_report
from mediamonitor.store import Store


def rows(*items):
    return [{"country": c, "day": d, "count": n} for c, d, n in items]


def test_daily_series_fills_missing_days_with_zero():
    days, series = daily_series(rows(("NL", "2026-08-01", 2), ("NL", "2026-08-04", 5), ("BE", "2026-08-02", 1)),
                                ["NL", "BE", "DE"])
    assert days[0] == date(2026, 8, 1) and days[-1] == date(2026, 8, 4)
    assert series["NL"] == [2, 0, 0, 5]
    assert series["BE"] == [0, 1, 0, 0]
    assert series["DE"] == [0, 0, 0, 0]


def test_weekly_starts_monday():
    days = [date(2026, 8, 1) + __import__("datetime").timedelta(days=i) for i in range(10)]  # Sat 1 Aug .. Mon 10 Aug
    wk = weekly(days, [1] * 10)
    assert wk == [(date(2026, 7, 27), 2), (date(2026, 8, 3), 7), (date(2026, 8, 10), 1)]


def test_before_after_needs_full_windows():
    days = [date(2026, 8, 1) + __import__("datetime").timedelta(days=i) for i in range(20)]
    vals = [1] * 10 + [3] * 10  # jump on 11 Aug
    assert before_after(days, vals, date(2026, 8, 11)) == (1.0, 3.0)
    assert before_after(days, vals, date(2026, 8, 3)) == (None, 1.0)  # not enough days before


def test_write_report(tmp_path, config_file, load_fixture):
    cfg = load_config(config_file)
    store = Store(cfg.database)
    store.upsert_counts("NL", [DayCount(f"2026-08-{d:02d}", d % 3, 1000) for d in range(1, 29)])
    arts = parse_articles(load_fixture("artlist.json"))
    store.upsert_articles("NL", arts)
    store.save_classification(arts[0].url, True, "supportive", "original_reporting", 5, "About the protest", "m",
                              subtopic="ME/CFS")
    store.save_classification(arts[2].url, False, "neutral", "other", 1, "Unrelated", "m")

    path = write_report(cfg, store, tmp_path / "out")
    page = path.read_text()
    assert "Netherlands" in page and "Belgium" in page
    assert "Before and after your actions" in page
    assert "supportive 1" in page
    assert "not relevant" in page
    assert "Mainly about" in page and "ME/CFS 1" in page
    assert "<script" not in page
    csv_text = (tmp_path / "out" / "articles.csv").read_text()
    assert "nos.nl" in csv_text and ",10.0," in csv_text  # tier 1 weight
    weekly_csv = (tmp_path / "out" / "weekly_counts.csv").read_text().splitlines()
    assert weekly_csv[0] == "week_start,NL,BE"


def test_report_escapes_html(tmp_path, config_file):
    cfg = load_config(config_file)
    store = Store(cfg.database)
    store.upsert_counts("NL", [DayCount("2026-08-01", 1, 10)])
    from mediamonitor.gdelt import Article
    from datetime import datetime, timezone
    store.upsert_articles("NL", [Article("https://x.nl/a", "<script>alert(1)</script>", "x.nl", "Dutch",
                                          "Netherlands", datetime(2026, 8, 1, tzinfo=timezone.utc))])
    page = write_report(cfg, store, tmp_path / "out").read_text()
    assert "<script>alert" not in page
