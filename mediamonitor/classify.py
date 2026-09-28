"""Optional: label each article with Claude.

Labels:
- relevant: is the article really about the topic, or a false keyword match?
- stance: supportive / neutral / critical / mixed, toward the organisation or its cause
- category: what kind of journalism it is (investigative, rewrite, etc.)
- depth: 1 (passing mention) to 5 (the article is mainly about the topic)
- subtopic (optional): which of the configured subtopics it is mainly about

Needs the `anthropic` package (`pip install -e .[llm]`) and an API key.
Each article is one API call. Labels are a model's judgement from the title
and (if it can be fetched) the article's opening text. Spot-check them.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from html.parser import HTMLParser

from .config import Config
from .store import Store

STANCES = ["supportive", "neutral", "critical", "mixed"]
CATEGORIES = [
    "investigative",      # original digging, new facts, named sources, documents
    "original_reporting", # own reporting on an event (e.g. a reporter at the protest)
    "interview_feature",  # profile, interview, long read
    "opinion",            # op-ed, column, editorial, letter
    "wire_rewrite",       # agency copy or a light rewrite of another outlet's story
    "low_quality",        # SEO filler, AI-generated content farms, aggregator spam
    "other",
]
TEXT_CHARS = 6000



def build_schema(subtopics: list[str]) -> dict:
    props = {
        "relevant": {"type": "boolean"},
        "stance": {"type": "string", "enum": STANCES},
        "category": {"type": "string", "enum": CATEGORIES},
        "depth": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "rationale": {"type": "string"},
    }
    if subtopics:
        props["subtopic"] = {"type": "string", "enum": [*subtopics, "several", "none"]}
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


DEFAULT_STANCE_GUIDE = (
    '"supportive" if it presents the organisation or cause favourably or mostly in its own terms; '
    '"critical" if it mainly questions, mocks or opposes it; "neutral" for straight reporting; '
    '"mixed" if it clearly gives both sides substantial weight.'
)

SYSTEM = """You label news articles for a media monitoring tool.

The tool tracks coverage of: {name}
Background on the topic: {description}

For the article you are given, decide:
- relevant: true only if the article actually concerns this topic or organisation, not an unrelated use of the same words.
- stance: the article's overall stance. {stance_guide} Judge the article as a whole, not the people it quotes.
- category: investigative = new facts found by the outlet's own digging; original_reporting = the outlet's own coverage of an event; interview_feature = profile, interview or long read; opinion = column, op-ed, editorial or letter; wire_rewrite = agency copy or a light rewrite of another outlet's story; low_quality = SEO filler, content-farm or machine-written text, aggregator spam; other = anything else.
- depth: 1 = passing mention, 3 = one substantial section, 5 = the article is mainly about the topic.
- rationale: one short sentence, in English.{subtopic_line}

The article may be in any language. If you only have a headline, give your best guess and say so in the rationale.
If relevant is false, set stance to neutral, category to other and depth to 1{subtopic_none}."""


def build_system(cfg: Config) -> str:
    if cfg.subtopics:
        subtopic_line = ("\n- subtopic: which of these the article is mainly about: "
                         + ", ".join(cfg.subtopics)
                         + '. Use "several" if it covers more than one about equally, "none" if none apply.')
        subtopic_none = ' and subtopic to "none"'
    else:
        subtopic_line = subtopic_none = ""
    return SYSTEM.format(
        name=cfg.name,
        description=cfg.description or "(none given)",
        stance_guide=cfg.stance_guide or DEFAULT_STANCE_GUIDE,
        subtopic_line=subtopic_line,
        subtopic_none=subtopic_none,
    )


class _TextExtractor(HTMLParser):
    """Collect text inside <p> tags. Crude, but works on most news sites."""

    def __init__(self):
        super().__init__()
        self._in_p = 0
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._in_p += 1
        elif tag in ("script", "style", "nav", "footer"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "p" and self._in_p:
            self._in_p -= 1
            self.parts.append("\n")
        elif tag in ("script", "style", "nav", "footer") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_p and not self._skip:
            self.parts.append(data)


def extract_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if len(line) > 30)


def fetch_text(url: str, timeout: float = 20) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mediamonitor)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(3_000_000)
            charset = resp.headers.get_content_charset() or "utf-8"
        return extract_text(raw.decode(charset, errors="replace"))
    except Exception:  # paywalls, timeouts, blocked bots: fall back to the headline
        return ""


def build_user_message(row, text: str) -> str:
    parts = [
        f"Outlet: {row['domain']}",
        f"Country: {row['country']}  Language: {row['language']}",
        f"Date: {row['seen_at'][:10]}",
        f"Headline: {row['title']}",
    ]
    if text:
        if len(text) > TEXT_CHARS:
            parts.append(f"Opening text (first {TEXT_CHARS} of {len(text)} characters):\n{text[:TEXT_CHARS]}")
        else:
            parts.append(f"Article text:\n{text}")
    else:
        parts.append("Article text: not available (only the headline).")
    return "\n".join(parts)


def classify_all(cfg: Config, store: Store, limit: int | None = None) -> int:
    try:
        import anthropic
    except ImportError:
        sys.exit("Classification needs the anthropic package: pip install -e '.[llm]'")

    client = anthropic.Anthropic()
    system = build_system(cfg)
    schema = build_schema(cfg.subtopics)
    rows = store.unclassified_articles(limit)
    done = 0
    for i, row in enumerate(rows, 1):
        text = fetch_text(row["url"]) if cfg.fetch_article_text else ""
        try:
            response = client.messages.create(
                model=cfg.model,
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": build_user_message(row, text)}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.RateLimitError:
            print("Rate limited; stopping. Run classify again later to continue.", file=sys.stderr)
            break
        except anthropic.APIStatusError as e:
            print(f"  skipped {row['url']}: API error {e.status_code}", file=sys.stderr)
            continue
        except anthropic.APIConnectionError as e:
            print(f"  skipped {row['url']}: connection error {e}", file=sys.stderr)
            continue

        if response.stop_reason in ("refusal", "max_tokens"):
            print(f"  skipped {row['url']}: stop_reason={response.stop_reason}", file=sys.stderr)
            continue
        text_block = next((b.text for b in response.content if b.type == "text"), None)
        if text_block is None:
            continue
        label = json.loads(text_block)
        store.save_classification(
            row["url"], label["relevant"], label["stance"], label["category"],
            label["depth"], label["rationale"], response.model, label.get("subtopic"),
        )
        done += 1
        print(f"  [{i}/{len(rows)}] {label['stance']:<10} {label['category']:<18} {label.get('subtopic') or '':<12} {row['title'][:60]}")
    return done
