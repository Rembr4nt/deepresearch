"""Research one topic from Python and save the report.

Run from the project root with the API keys in .env:
    python examples/basic_usage.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.deep_research import InteractiveDeepResearch

# Arguments left out come from config/config.yaml
researcher = InteractiveDeepResearch(interactive=False, max_queries=3, max_iteration=2)
report = researcher("Impact of artificial intelligence on modern healthcare systems")

Path("research_results.md").write_text(report, encoding="utf-8")
print("Saved research_results.md")
