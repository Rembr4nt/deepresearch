# Deep Research

Give it a research topic and it writes a cited Markdown report. It plans search queries, reads
the web, finds what is still missing, searches again, and then writes the report from the
sources that pass a relevance filter. You can use it from the command line, from Python, or
through a web UI that shows progress live.

Two reports it wrote are in [`examples/sample_reports/`](examples/sample_reports): 1,725 words
with 43 source links, and 1,834 words with 25 source links.

## How it works

| Step | What happens | Model or service |
|---|---|---|
| 1 | (Interactive mode) Asks 2-3 questions to narrow the topic and adds your answers to it | planning model |
| 2 | Writes search queries for the topic | planning model, JSON model to parse |
| 3 | Searches every query in parallel and summarizes long pages | Tavily, summarization model |
| 4 | Reads what was found, lists what is still missing as new queries, and searches those. Repeats up to `max_iteration` rounds, or stops early when nothing is missing | planning model, JSON model |
| 5 | Drops thin pages, removes duplicates, and keeps only sources whose rerank score passes the threshold | Voyage `rerank-2` |
| 6 | Writes the report from the kept sources, trimmed to fit the context budget, and removes the model's `<think>` reasoning | answer model |

Default models (Together AI): Llama 4 Maverick for planning, Llama 3.3 70B for summaries,
Llama 3.1 70B for JSON parsing, and DeepSeek-R1 for the report. The prompts for steps 2-6 are
in `config/prompts.yaml`.

## Requirements

- Python 3.10+
- API keys for [Together AI](https://together.ai), [Voyage AI](https://voyageai.com) and
  [Tavily](https://tavily.com). These are paid APIs, so every run uses credits.

## Install

```bash
git clone https://github.com/Rembr4nt/deepresearch.git
cd deepresearch
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then put your three keys in .env
```

## Usage

**Command line.** The report is saved to `results/<topic>.md`.

```bash
python -m src.research "Digital twins for energy efficiency in smart cities"
python -m src.research "AI regulation in the EU vs the US" --max-iteration 2 --max-queries 3
```

| Flag | Effect |
|---|---|
| `--max-queries N` | Search queries per round |
| `--max-search N` | Search results per query |
| `--max-iteration N` | Research rounds |
| `--thres X` | Minimum rerank score (0-1) to keep a source |
| `--max-tokens N` | Maximum output tokens per model call |
| `-o DIR` | Output folder (default `results`) |

Flags you leave out come from `config/config.yaml`. With `interactive: true` (the default) the
command line asks its questions in the terminal first.

**Web UI.** Live progress per step, clarifying questions in a dialog, cancel, and download as
Markdown, text, JSON or PDF. The form has its own defaults (5 queries, 5 results, 3 rounds).

```bash
cd web_interface
python start_server.py           # http://127.0.0.1:8000
```

**Python.** See [`examples/basic_usage.py`](examples/basic_usage.py).

```python
from src.deep_research import InteractiveDeepResearch

researcher = InteractiveDeepResearch(interactive=False, max_iteration=2)
report = researcher("Impact of AI on modern healthcare systems")
```

## Configuration

`config/config.yaml` holds the research settings, the model IDs and the context budget.
These environment variables override it: `PLANNING_MODEL`, `SUMMARIZATION_MODEL`,
`JSON_MODEL`, `ANSWER_MODEL`, `MAX_QUERIES`, `MAX_ITERATIONS` and `LOG_LEVEL`.

The model IDs are the ones Together AI served in July 2025. Together retires models over
time, so if a call fails with an unknown model, replace the ID in `config.yaml` with a current
one from [Together's model list](https://docs.together.ai/docs/serverless-models).

## Tests

```bash
pip install pytest httpx
python -m pytest tests
```

The tests run offline with fake API keys. They cover the `<think>` removal, the output file
names, the rerank filter (with a fake reranker) and the web server's health endpoint.

## Limitations

- Report quality was not measured against a benchmark or human ratings. The sample reports
  show what it produces.
- Token counts use the GPT-4 tokenizer for every model, so the context budget is approximate.
- The web UI keeps sessions in memory in one process, so nothing is kept after a restart.
- Search covers the public web through Tavily only, with no paywalled papers or private
  documents.

## Credits

Built on [open_deep_research](https://github.com/togethercomputer/open_deep_research) by
Together AI (MIT License). `src/data_types.py`, `src/tavily_search.py`, the research loop
(plan, search, check gaps, write) and several prompts are adapted from it. This project adds
the Voyage rerank filter (in place of Together's LLM filter), the thin-page filter, chunked
summaries for very long pages, the token budget that shrinks the context and retries when a
call is too long, the command line tool, and the web UI with clarifying questions in the
browser.

## License

MIT, see [LICENSE](LICENSE).
