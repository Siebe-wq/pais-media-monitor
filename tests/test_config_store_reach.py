from datetime import date

from mediamonitor.config import load_config
from mediamonitor.gdelt import parse_articles, parse_timeline
from mediamonitor.reach import ReachTable
from mediamonitor.store import Store


def test_load_config(config_file):
    cfg = load_config(config_file)
    assert cfg.gdelt_query() == '(PauseAI OR "Pause AI")'
    assert [c.code for c in cfg.countries] == ["NL", "BE"]
    assert cfg.actions[0].date == date(2026, 8, 15)
    assert cfg.database == config_file.parent / "test.db"
    assert cfg.model == "claude-opus-5"


def test_single_term_query(config_file):
    cfg = load_config(config_file)
    cfg.terms = ["PauseAI"]
    assert cfg.gdelt_query() == "PauseAI"


def test_store_is_idempotent(tmp_path, load_fixture):
    store = Store(tmp_path / "db.sqlite")
    arts = parse_articles(load_fixture("artlist.json"))
    assert store.upsert_articles("NL", arts) == 3
    assert store.upsert_articles("NL", arts) == 0
    counts = parse_timeline(load_fixture("timeline.json"))
    store.upsert_counts("NL", counts)
    store.upsert_counts("NL", counts)
    assert len(store.daily_counts()) == 3
    assert len(store.unclassified_articles()) == 3
    store.save_classification(arts[0].url, True, "neutral", "original_reporting", 4, "x", "m")
    assert len(store.unclassified_articles()) == 2


def test_reach_matches_subdomains():
    r = ReachTable({"nos.nl": 1, "www.bbc.co.uk": 1, "nu.nl": 2}, {1: 10.0, 2: 3.0}, 1.0)
    assert r.tier("nos.nl") == 1
    assert r.tier("www.nos.nl") == 1
    assert r.tier("news.bbc.co.uk") == 1
    assert r.tier("co.uk") is None
    assert r.weight("nu.nl") == 3.0
    assert r.weight("unknown.example") == 1.0
