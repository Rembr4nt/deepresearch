# Adapted from Together AI open_deep_research (MIT License, Copyright (c) 2025 Together). See LICENSE.

from pydantic import BaseModel, Field
from dataclasses import dataclass
from typing import Optional, List

class ResearchPlan(BaseModel):
    queries: list[str] = Field(
        description="A list of search queries to thoroughly research the topic")

class SourceList(BaseModel):
    sources: list[int] = Field(
        description="A list of source numbers from the search results")

@dataclass(frozen=True, kw_only=True)
class SearchResult:
    title: str
    link: str
    content: str
    raw_content: Optional[str] = None

    def __str__(self, include_raw=True):
        result = f"Title: {self.title}\n" f"Link: {self.link}\n" f"Content: {self.content}"
        if include_raw and self.raw_content:
            result += f"\nRaw Content: {self.raw_content}"
        return result

    def short_str(self):
        return self.__str__(include_raw=False)

@dataclass(frozen=True, kw_only=True)
class SearchResults:
    results: list[SearchResult]

    def __str__(self, short=False):
        if short:
            result_strs = [result.short_str() for result in self.results]
        else:
            result_strs = [str(result) for result in self.results]
        return "\n\n".join(f"[{i+1}] {result_str}" for i, result_str in enumerate(result_strs))

    def __add__(self, other):
        return SearchResults(results=self.results + other.results)

    def short_str(self):
        return self.__str__(short=True)

@dataclass(frozen=True, kw_only=True)
class DeepResearchResult(SearchResult):
    """Wrapper on top of SearchResults to adapt it to the DeepResearch.

    This class extends the basic SearchResult by adding a filtered version of the raw content
    that has been processed and refined for the specific research context. It maintains
    the original search result while providing additional research-specific information.

    Attributes:
        summarized_content: A processed version of the raw content that has been filtered
                             and refined for relevance to the research topic
    """

    summarized_content: str

    def __str__(self):
        return f"Title: {self.title}\n" f"Link: {self.link}\n" f"Refined Content: {self.summarized_content}"

    def short_str(self):
        return f"Title: {self.title}\nLink: {self.link}\nRaw Content: {self.content[:10000]}"

@dataclass(frozen=True, kw_only=True)
class DeepResearchResults(SearchResults):
    results: list[DeepResearchResult]

    def __add__(self, other):
        return DeepResearchResults(results=self.results + other.results)

    def dedup(self):
        def deduplicate_by_link(results):
            seen_links = set()
            unique_results = []

            for result in results:
                if result.link not in seen_links:
                    seen_links.add(result.link)
                    unique_results.append(result)

            return unique_results

        return DeepResearchResults(results=deduplicate_by_link(self.results))