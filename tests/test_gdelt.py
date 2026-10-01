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


def test_articles_one_request_when_under_cap(monkeypatch, load_fixture):
    calls = []
    client = GdeltClient(min_interval=0)
    monkeypatch.setattr(client, "_get", lambda params: calls.append(params) or load_fixture("artlist.json"))
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 29, tzinfo=timezone.utc)
    arts, hit_cap = client.articles("PauseAI", "netherlands", start, end)
    assert len(calls) == 1 and len(arts) == 3 and not hit_cap
    assert calls[0]["startdatetime"] == "20260701000000"
    assert calls[0]["query"] == "PauseAI sourcecountry:netherlands"


def test_articles_halves_period_when_cap_is_hit(monkeypatch):
    from datetime import timedelta
    full = {"articles": [{"url": f"u{i}", "title": "t", "domain": "d", "language": "", "sourcecountry": "",
                          "seendate": "20260801T000000Z"} for i in range(250)]}
    small = {"articles": [{"url": "x", "title": "t", "domain": "d", "language": "", "sourcecountry": "",
                           "seendate": "20260801T000000Z"}]}
    calls = []

    def fake_get(params):
        calls.append((params["startdatetime"], params["enddatetime"]))
        return full if len(calls) == 1 else small

    client = GdeltClient(min_interval=0)
    monkeypatch.setattr(client, "_get", fake_get)
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    arts, hit_cap = client.articles("x", None, start, start + timedelta(days=10))
    assert calls == [("20260801000000", "20260811000000"),
                     ("20260801000000", "20260806000000"),
                     ("20260806000000", "20260811000000")]
    assert len(arts) == 2 and not hit_cap


def test_stops_at_deadline():
    import time
    client = GdeltClient(min_interval=0, deadline=time.monotonic() - 1)
    with pytest.raises(GdeltError, match="time budget"):
        client._get({"query": "x"})


def test_backs_off_on_429_then_succeeds(monkeypatch):
    import urllib.error
    responses = [
        urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None),
        FakeResponse(b"Please limit requests to one every 5 seconds"),
        FakeResponse(b'{"articles": []}'),
    ]

    def fake_urlopen(req, timeout):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(gdelt.urllib.request, "urlopen", fake_urlopen)
    sleeps = []
    client = GdeltClient(min_interval=0, backoff=20, sleep=sleeps.append)
    assert client._get({"query": "x"}) == {"articles": []}
    assert sleeps == [20, 40]


def test_gives_up_after_retries(monkeypatch):
    import urllib.error

    def always_429(req, timeout):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(gdelt.urllib.request, "urlopen", always_429)
    client = GdeltClient(min_interval=0, retries=3, sleep=lambda s: None)
    with pytest.raises(GdeltError, match="after 3 tries: HTTP 429"):
        client._get({"query": "x"})


def test_other_http_errors_are_not_retried(monkeypatch):
    import urllib.error
    calls = []

    def bad_request(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError("u", 400, "Bad Request", {}, None)

    monkeypatch.setattr(gdelt.urllib.request, "urlopen", bad_request)
    client = GdeltClient(min_interval=0, sleep=lambda s: None)
    with pytest.raises(GdeltError, match="HTTP 400"):
        client._get({"query": "x"})
    assert len(calls) == 1


def test_merge_counts_sums_groups():
    from mediamonitor.cli import merge_counts
    from mediamonitor.gdelt import DayCount
    merged = merge_counts([[DayCount("2026-09-01", 2, 100), DayCount("2026-09-02", 1, 90)],
                           [DayCount("2026-09-01", 3, 100)]])
    assert [(d.day, d.count, d.total_monitored) for d in merged] == [
        ("2026-09-01", 5, 100), ("2026-09-02", 1, 90)]
