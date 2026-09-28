import io
from datetime import datetime, timezone

import pytest

from mediamonitor import gdelt
from mediamonitor.gdelt import GdeltClient, GdeltError, parse_articles, parse_timeline


def test_parse_articles(load_fixture):
    arts = parse_articles(load_fixture("artlist.json"))
    assert len(arts) == 3
    assert arts[1].domain == "nu.nl"
    assert arts[1].seen_at == datetime(2026, 8, 16, 9, tzinfo=timezone.utc)


def test_parse_articles_empty():
    assert parse_articles({}) == []


def test_parse_timeline_sums_intervals_into_days(load_fixture):
    days = parse_timeline(load_fixture("timeline.json"))
    assert [(d.day, d.count, d.total_monitored) for d in days] == [
        ("2026-08-15", 3, 2100), ("2026-08-16", 0, 900), ("2026-08-18", 4, 950)]


def test_build_query():
    assert GdeltClient.build_query("(a OR b)", "netherlands") == "(a OR b) sourcecountry:netherlands"
    assert GdeltClient.build_query("a", None) == "a"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_plain_text_error_raises(monkeypatch):
    monkeypatch.setattr(gdelt.urllib.request, "urlopen",
                        lambda req, timeout: FakeResponse(b"Your search contained invalid characters."))
    client = GdeltClient(min_interval=0)
    with pytest.raises(GdeltError, match="invalid characters"):
        client._get({"query": "x", "mode": "artlist"})


def test_articles_splits_into_windows(monkeypatch, load_fixture):
    calls = []
    client = GdeltClient(min_interval=0)
    monkeypatch.setattr(client, "_get", lambda params: calls.append(params) or load_fixture("artlist.json"))
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 20, tzinfo=timezone.utc)
    arts, hit_cap = client.articles("PauseAI", "netherlands", start, end, window_days=7)
    assert len(calls) == 3
    assert calls[0]["startdatetime"] == "20260801000000"
    assert calls[-1]["enddatetime"] == "20260820000000"
    assert calls[0]["query"] == "PauseAI sourcecountry:netherlands"
    assert len(arts) == 9 and not hit_cap
