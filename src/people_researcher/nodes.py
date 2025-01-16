from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import NotRequired, TypedDict, cast

import logfire
from pydantic import BaseModel, Field
from pydantic_graph import BaseNode, End, GraphRunContext
from tavily import AsyncTavilyClient

from people_researcher.prompts import (
    EXTRACTION_PROMPT,
    INFO_PROMPT,
    QUERY_WRITER_PROMPT,
    REFLECTION_PROMPT,
)
from people_researcher.state import PersonInfo, PersonState
from pydantic_ai import Agent

# Configure logfire
logfire.configure()

tavily_client = AsyncTavilyClient()


class ReflectionOutput(BaseModel):
    """Reflection on information completeness."""

    is_satisfactory: bool = Field(
        description="True if all required fields are well populated, False otherwise"
    )
    missing_fields: list[str] = Field(
        description="List of field names that are missing or incomplete"
    )
    search_queries: list[str] = Field(
        description="If is_satisfactory is False, provide 1-3 targeted search queries to find the missing information"
    )
    reasoning: str = Field(description="Brief explanation of the assessment")


class TavilyResult(TypedDict):
    """Individual result from Tavily API."""

    url: str
    title: str
    content: str
    raw_content: NotRequired[str]


class TavilyResponse(TypedDict):
    """Response from Tavily API."""

    results: list[TavilyResult]


class Queries(BaseModel):
    """Generated search queries."""

    queries: list[str] = Field(
        description="List of search queries to find information about the person.",
    )


query_agent = Agent(
    "openai:gpt-4o",
    result_type=Queries,
    name="query_generator",
    system_prompt=QUERY_WRITER_PROMPT,
)

research_notes_agent = Agent(
    "openai:gpt-4o",
    result_type=str,
    name="researcher",
    system_prompt=INFO_PROMPT,
)

extraction_agent = Agent(
    "openai:gpt-4o",
    result_type=PersonInfo,
    name="extractor",
    system_prompt=EXTRACTION_PROMPT,
)


reflection_agent = Agent(
    "openai:gpt-4o",
    result_type=ReflectionOutput,
    name="reflection",
    system_prompt=REFLECTION_PROMPT,
)


def deduplicate_and_format_sources(
    search_response: TavilyResponse | list[TavilyResponse],
    max_tokens: int = 1000,
    include_raw_content: bool = True,
) -> str:
    """Format and deduplicate search results from Tavily."""
    with logfire.span(
        "deduplicating_sources",
        num_responses=len(search_response) if isinstance(search_response, list) else 1,
    ):
        # Convert input to list of results
        sources_list: list[TavilyResult] = []
        if not isinstance(search_response, list):
            sources_list = search_response["results"]
        else:
            for response in search_response:
                sources_list.extend(response["results"])

        # Deduplicate by URL
        unique_sources: dict[str, TavilyResult] = {}
        for source in sources_list:
            if source["url"] not in unique_sources:
                unique_sources[source["url"]] = source

        logfire.info(
            "deduplicated {initial} sources to {final} unique sources",
            initial=len(sources_list),
            final=len(unique_sources),
        )

        # Format output
        formatted_text = "Sources:\n\n"
        for source in unique_sources.values():
            formatted_text += f"Source {source['title']}:\n===\n"
            formatted_text += f"URL: {source['url']}\n===\n"
            formatted_text += (
                f"Most relevant content from source: {source['content']}\n===\n"
            )
            if include_raw_content:
                raw_content = source.get("raw_content")
                if raw_content is None:
                    raw_content = ""
                elif len(raw_content) > max_tokens * 4:
                    raw_content = raw_content[: max_tokens * 4] + "... [truncated]"
                formatted_text += f"Full source content limited to {max_tokens} tokens: {raw_content}\n\n"

        return formatted_text.strip()


@dataclass
class GenerateQueries(BaseNode[PersonState, None, PersonInfo]):
    """Node to generate search queries for person information."""

    async def run(self, ctx: GraphRunContext[PersonState]) -> Research:
        with logfire.span("generating_queries", person=ctx.state.person_str):
            result = await query_agent.run(
                ctx.state.person_str,
            )
            ctx.state.search_queries = result.data.queries
            logfire.info("generated {num} search queries", num=len(result.data.queries))
            return Research()


@dataclass
class Research(BaseNode[PersonState, None, PersonInfo]):
    """Node to execute web searches and process results."""

    async def run(self, ctx: GraphRunContext[PersonState]) -> Extract:
        """Execute web searches and process results."""
        with logfire.span("research_phase", num_queries=len(ctx.state.search_queries)):
            # Execute web searches using Tavily
            search_futures: list[Awaitable[TavilyResponse]] = []
            for query in ctx.state.search_queries:
                logfire.debug("querying tavily: {query}", query=query)
                search_futures.append(
                    cast(
                        Awaitable[TavilyResponse],
                        tavily_client.search(
                            query,
                            search_depth="basic",
                            days=360,
                            max_results=3,
                            include_raw_content=True,
                            topic="general",
                        ),
                    )
                )

            # Execute searches concurrently
            search_results: list[TavilyResponse] = await asyncio.gather(*search_futures)

            # Format and deduplicate sources
            source_str = deduplicate_and_format_sources(
                search_results, max_tokens=1000, include_raw_content=True
            )

            logfire.debug("processing search results with research agent")
            result = await research_notes_agent.run(
                source_str,
            )
            ctx.state.notes.append(str(result.data))
            logfire.info(
                "added {length} characters of research notes",
                length=len(str(result.data)),
            )
            return Extract()


@dataclass
class Extract(BaseNode[PersonState, None, PersonInfo]):
    """Node to extract person information from research notes."""

    async def run(self, ctx: GraphRunContext[PersonState]) -> Reflect:
        with logfire.span("extracting_information"):
            # Format all notes
            all_notes = "\n\n".join(ctx.state.notes)
            logfire.debug(
                "processing {length} characters of notes", length=len(all_notes)
            )

            result = await extraction_agent.run(
                all_notes,
            )
            ctx.state.info = result.data
            logfire.info("extracted person information", info=result.data)
            return Reflect()


@dataclass
class Reflect(BaseNode[PersonState, None, PersonInfo]):
    """Node to reflect on the completeness of gathered information."""

    def _create_default_info(self) -> PersonInfo:
        """Create default PersonInfo when no info is available."""
        return PersonInfo(
            years_experience=0,
            current_company="Unknown",
            role="Unknown",
            prior_companies=[],
            notes="No information available",
        )

    async def run(
        self, ctx: GraphRunContext[PersonState]
    ) -> End[PersonInfo] | GenerateQueries:
        with logfire.span("reflection_phase", cycle=ctx.state.reflection_count):
            result = await reflection_agent.run(
                json.dumps(
                    {
                        "notes": "\n".join(ctx.state.notes),
                        "info": ctx.state.info.model_dump_json()
                        if ctx.state.info is not None
                        else None,
                    },
                    indent=2,
                ),
            )

            logfire.info(
                "reflection result: {is_satisfactory}",
                is_satisfactory=result.data.is_satisfactory,
            )

            if result.data.is_satisfactory:
                return End(
                    ctx.state.info if ctx.state.info else self._create_default_info()
                )

            # Allow up to 2 reflection cycles
            if ctx.state.reflection_count < 2:
                ctx.state.reflection_count += 1
                ctx.state.search_queries = result.data.search_queries
                logfire.info(
                    "starting reflection cycle {cycle} with {num} new queries",
                    cycle=ctx.state.reflection_count,
                    num=len(result.data.search_queries),
                )
                return GenerateQueries()
            else:
                logfire.info("max reflection cycles reached, ending with current info")
                return End(
                    ctx.state.info if ctx.state.info else self._create_default_info()
                )
