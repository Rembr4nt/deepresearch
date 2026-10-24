"""Offline tests: fake API keys, a fake reranker, and no network calls."""

import asyncio
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Fake keys so the web server's startup key check passes. No test calls an API.
for key in ("TOGETHER_API_KEY", "VOYAGE_API_KEY", "TAVILY_API_KEY"):
    os.environ.setdefault(key, "offline-test-key-0000")

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "web_interface")]

import pytest

from src import deep_research
from src.data_types import DeepResearchResult, DeepResearchResults
from src.research import create_safe_filename, get_versioned_filepath
from src.utils import remove_thinking_tags


@pytest.mark.parametrize("raw, clean", [
    ("<think>plan</think>\n# Report", "# Report"),
    ("<thinking>a</thinking>Intro <think>b</think>body", "Intro body"),
    ("reasoning with no opening tag</think>\n# Report", "# Report"),
    ("# Report only", "# Report only"),
])
def test_remove_thinking_tags(raw, clean):
    assert remove_thinking_tags(raw) == clean


def test_output_file_names(tmp_path):
    assert create_safe_filename("AI in Healthcare: 2025?") == "ai_in_healthcare_2025"
    first = get_versioned_filepath("Solar power", str(tmp_path))
    Path(first).write_text("x")
    second = get_versioned_filepath("Solar power", str(tmp_path))
    assert (Path(first).name, Path(second).name) == ("solar_power.md", "solar_power_2.md")


def test_topic_check_allows_plain_words():
    for topic in ("Latest update on fusion energy", "Trade union policy in the EU", "Immune system (2025)"):
        assert deep_research.validate_research_topic(topic) == topic
    with pytest.raises(deep_research.ValidationError):
        deep_research.validate_research_topic("<script>alert(1)</script> solar")


def _result(link, words=60):
    text = " ".join(["photovoltaic"] * words)
    return DeepResearchResult(title=link, link=link, content=text, summarized_content=text)


@pytest.mark.parametrize("use_async", [False, True])
def test_rerank_filter(monkeypatch, use_async):
    scores = {"https://a.org": 0.9, "https://b.org": 0.2}

    def fake_rerank(topic, documents):
        link = lambda doc: doc.split("Link: ")[1].split("\n")[0]
        return SimpleNamespace(results=[
            SimpleNamespace(document=d, relevance_score=scores[link(d)]) for d in documents])

    monkeypatch.setattr(deep_research, "llm_rerank", fake_rerank)
    researcher = deep_research.InteractiveDeepResearch.__new__(deep_research.InteractiveDeepResearch)
    researcher.config = deep_research.ResearchConfig()
    researcher.logger = logging.getLogger("test")
    researcher.rerank_score_threshold = 0.6
    researcher.progress_callback = None

    results = DeepResearchResults(results=[
        _result("https://a.org"), _result("https://a.org"),  # duplicate
        _result("https://b.org"),                             # low rerank score
        _result("https://thin.org", words=5),                 # too little text
    ])
    if use_async:
        kept = asyncio.run(researcher.filter_results_with_rerank_async("solar panels", results, "filtering", 0.9))
    else:
        kept = researcher.filter_results_with_rerank("solar panels", results)
    assert [r.link for r in kept.results] == ["https://a.org"]


def test_web_server_serves_health_and_page():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:  # runs startup and shutdown too
        assert client.get("/health").json()["status"] == "healthy"
        page = client.get("/")
        assert page.status_code == 200 and "purify.min.js" in page.text
