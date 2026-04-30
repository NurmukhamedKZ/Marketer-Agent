from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import BaseTool
from mcp import ClientSession
from urllib.parse import urlparse
import logging
import asyncio
import httpx
import html
import os
import re
import shlex

mcp = FastMCP("Web-Search", instructions="Server for Web-searching ")

_cmd = "python -m app.mcp.web_search"


def _client() -> MultiServerMCPClient:
    parts = shlex.split(_cmd)
    return MultiServerMCPClient(
        {"web_search": {"command": parts[0], "args": parts[1:], "transport": "stdio"}}
    )


@asynccontextmanager
async def web_search_session() -> AsyncIterator[tuple[ClientSession, list[BaseTool]]]:
    """Open a persistent web_search MCP session and yield (session, tools).

    The subprocess stays alive for the duration of the context — no per-call respawn.
    """
    async with _client().session("web_search") as session:
        tools = await load_mcp_tools(session, server_name="web_search")
        yield session, tools

logger = logging.getLogger(__name__)

_USER_AGENT_2 = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
_MAX_REDIRECTS = 5


@mcp.tool
async def web_search(query: str, count: int = 5) -> str:
    """
    Search the public web (Searxng meta-search) and return ranked results
    as titles, URLs, and snippets. Use this to research trending topics,
    verify claims, or discover what audiences are discussing right now.

    Args:
        query: 3-8 keywords describing what you want to find. Plain text,
            no quotes, no boolean operators. Optimised for snippet quality,
            not exact-match.
            Good: "ai sdr agents 2026 adoption"
            Bad:  "What are the latest trends in AI SDR agents?" (too long,
                  question form hurts ranking)
        count: Number of results to return. Range: 1-10. Default: 5.
            Values >10 are silently clamped to 20 server-side, but the
            agent should stay within 1-10 for token efficiency.

    Returns:
        Plain-text block, one result per 2-3 lines:
            "1. <title>
                <url>
                <snippet>"
        Returns "No results found for: <query>" if nothing matches.
        Returns "❌ Web search error: <reason>" on transport/HTTP failure.

    Edge cases:
        - Snippets may be missing for some results; URL and title are always present.
        - Results are not deduplicated by domain — the same site can appear twice.
        - For full page contents, follow up with web_fetch on a specific URL.
    """
    _base_url = os.getenv("SEARXNG_URL", "http://localhost:8888")

    logger.info("TOOL ▶ web_search called — query=%r, count=%d", query, count)
    try:
        n = min(max(count, 1), 20)
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{_base_url}/search",
                params={"q": query, "format": "json", "language": "en"},
            )
            r.raise_for_status()

        results = r.json().get("results", [])
        if not results:
            logger.info("TOOL ▶ web_search — no results for query=%r", query)
            return f"No results found for: {query}"

        lines = [f"Search results for: {query}\n"]
        for i, item in enumerate(results[:n], 1):
            lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
            if snippet := item.get("content"):
                lines.append(f"   {snippet}")

        logger.info("TOOL ▶ web_search returned %d results for query=%r", min(len(results), n), query)
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("web_search failed for query=%r", query)
        return f"❌ Web search error: {exc}"

# ── HTML helpers ──────────────────────────────────────────────────────────────

def _strip_tags(text: str) -> str:
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)
    
@mcp.tool
async def web_fetch(url: str) -> str:
    """
    Fetch a single URL and return its readable text content (HTML stripped,
    links/headings/lists preserved as Markdown). Use this AFTER web_search
    when a snippet looks promising but you need the full article — quotes,
    statistics, primary-source detail.

    Args:
        url: Full http(s) URL, exactly as returned by web_search. Must include
            scheme. Example: "https://example.com/blog/post".
            Other schemes (file://, ftp://, javascript:) are rejected.

    Returns:
        Cleaned text of the page, up to 15,000 characters. If the page
        exceeds that, output is truncated and ends with
        "[Truncated at 15000 chars]".
        For JSON responses, returns pretty-printed JSON.
        Returns "❌ Invalid URL: <reason>" on bad input.
        Returns "❌ Failed to fetch <url>: <reason>" on network/HTTP error.

    Edge cases:
        - Some sites block scrapers (403/Cloudflare); on failure try a
          different result from web_search rather than retrying.
        - Do NOT fetch the same URL twice in one run — the result is deterministic.
        - Heavy SPA pages may return mostly script noise; prefer article URLs
          over homepage URLs when researching a topic.
        - One fetch ≈ 15k chars of context; budget accordingly.
    """
    _max_chars = 15000
    logger.info("TOOL ▶ web_fetch called — url=%r", url)

    is_valid, error_msg = _validate_url(url)
    if not is_valid:
        return f"❌ Invalid URL: {error_msg}"

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            timeout=30.0,
        ) as client:
            # r = await client.get(url, headers={
            #     "User-Agent": _USER_AGENT,
            #     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            #     "Accept-Language": "en-US,en;q=0.9",
            #     "Accept-Encoding": "gzip, deflate, br",
            # })
            r = await client.get(url, headers={"User-Agent": _USER_AGENT_2})
            r.raise_for_status()

        ctype = r.headers.get("content-type", "")

        if "application/json" in ctype:
            import json
            text = json.dumps(r.json(), indent=2, ensure_ascii=False)
        elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
            # Convert links and headings before stripping tags
            raw = r.text
            raw = re.sub(
                r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                lambda m: f'[{_strip_tags(m[2])}]({m[1]})',
                raw, flags=re.I,
            )
            raw = re.sub(
                r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n',
                raw, flags=re.I,
            )
            raw = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', raw, flags=re.I)
            raw = re.sub(r'</(p|div|section|article)>', '\n\n', raw, flags=re.I)
            raw = re.sub(r'<(br|hr)\s*/?>', '\n', raw, flags=re.I)
            text = _normalize(_strip_tags(raw))
        else:
            text = r.text

        truncated = len(text) > _max_chars
        if truncated:
            text = text[:_max_chars]

        suffix = f"\n\n[Truncated at {_max_chars} chars]" if truncated else ""
        logger.info("TOOL ▶ web_fetch returned %d chars from url=%r (truncated=%s)", len(text), url, truncated)
        return text + suffix

    except Exception as exc:
        logger.exception("web_fetch failed for url=%r", url)
        return f"❌ Failed to fetch {url}: {exc}"

if __name__ == "__main__":
    mcp.run()