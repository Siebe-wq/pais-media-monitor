import json
import sys
import types

from mediamonitor import classify
from mediamonitor.config import load_config
from mediamonitor.gdelt import parse_articles
from mediamonitor.store import Store


def test_extract_text_keeps_paragraphs_only():
    html = """<html><head><script>var x = 'nope';</script></head><body>
    <nav><p>Menu item that is long enough to pass the filter maybe</p></nav>
    <p>Protesters gathered outside the parliament on Saturday to demand a pause.</p>
    <p>Short</p></body></html>"""
    assert classify.extract_text(html) == "Protesters gathered outside the parliament on Saturday to demand a pause."


def test_user_message_marks_excerpt():
    row = {"domain": "nos.nl", "country": "NL", "language": "Dutch",
           "seen_at": "2026-08-15T12:00:00+00:00", "title": "Kop"}
    msg = classify.build_user_message(row, "a" * (classify.TEXT_CHARS + 10))
    assert f"first {classify.TEXT_CHARS} of" in msg
    assert "only the headline" in classify.build_user_message(row, "")


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        label = {"relevant": True, "stance": "supportive", "category": "original_reporting",
                 "depth": 4, "rationale": "Reports on the protest."}
        block = types.SimpleNamespace(type="text", text=json.dumps(label))
        return types.SimpleNamespace(stop_reason="end_turn", content=[block], model=kwargs["model"])


def test_classify_all_with_fake_client(monkeypatch, config_file, load_fixture):
    fake_messages = FakeMessages()
    fake_client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=fake_messages))
    fake_module = types.SimpleNamespace(
        Anthropic=lambda: fake_client,
        RateLimitError=type("RateLimitError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    cfg = load_config(config_file)
    cfg.fetch_article_text = False
    store = Store(cfg.database)
    store.upsert_articles("NL", parse_articles(load_fixture("artlist.json")))

    assert classify.classify_all(cfg, store, limit=2) == 2
    assert len(store.unclassified_articles()) == 1
    call = fake_messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"]["format"]["schema"] == classify.SCHEMA
    assert "PauseAI" in call["system"]
