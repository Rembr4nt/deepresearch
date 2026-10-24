import asyncio
import logging
import os
import re
from functools import cache
from dotenv import load_dotenv

os.environ.setdefault("TOGETHER_NO_BANNER", "1")  # the 1.x SDK prints an upgrade banner on import
from together import Together
from voyageai import Client as VoyageClient

# Keys come from .env or the environment; validate_api_keys() reports missing ones
load_dotenv()

logger = logging.getLogger(__name__)


# Clients are created on first use, so imports and --help work without keys
@cache
def _together():
    return Together(api_key=os.getenv("TOGETHER_API_KEY"))


@cache
def _voyage():
    return VoyageClient(api_key=os.getenv("VOYAGE_API_KEY"))


def llm_call(
    model,
    system_prompt,
    message,
    response_format=None,
    max_completion_tokens=None
):
    response = _together().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        temperature=0.0,
        response_format=response_format,
        max_tokens=max_completion_tokens
    )
    return response.choices[0].message.content

def llm_rerank(
    topic,
    documents,
    model="rerank-2",
    top_k_documents=None
):
    response = _voyage().rerank(
        query=topic,
        documents=documents,
        model=model,
        top_k=top_k_documents
    )
    return response

async def llm_call_async(
    model,
    system_prompt,
    message,
    response_format=None,
    max_completion_tokens=None
):
    """Run llm_call in a worker thread so the event loop stays free; cancellable, 5 min timeout."""
    if not model or not system_prompt or not message:
        raise ValueError("Model, system prompt, and message are required")

    timeout_seconds = 300
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                llm_call,
                model=model,
                system_prompt=system_prompt,
                message=message,
                response_format=response_format,
                max_completion_tokens=max_completion_tokens,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.error(f"LLM call timed out after {timeout_seconds}s")
        raise
    except asyncio.CancelledError:
        logger.info("LLM call cancelled")
        raise
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise

def remove_thinking_tags(answer):
    """Remove model reasoning: <think>/<thinking> blocks, and any text before a closing tag
    that has no opening tag (some APIs drop the opening <think>)."""
    for tag in ("thinking", "think"):
        answer = re.sub(rf"<{tag}>.*?</{tag}>", "", answer, flags=re.S)
        if f"</{tag}>" in answer:
            answer = answer.split(f"</{tag}>")[-1]
    return answer.strip()
