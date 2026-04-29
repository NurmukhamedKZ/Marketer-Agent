from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from urllib.parse import urlparse
import logging
import asyncio
import httpx
import html
import os
import re
mcp = FastMCP("Web-Search", instructions="Server for Web-searching ")

logger = logging.getLogger(__name__)

_USER_AGENT_2 = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
_MAX_REDIRECTS = 5


@mcp.tool
async def web_search(query: str, count: int = 5) -> str:
    """
    Search the internet and return titles, URLs, and snippets.

    Use this tool when `rag_search` returns no relevant results and the user
    asks about something that may be available on the web (news, general knowledge,
    university events not yet in the knowledge base, etc.).

    Args:
        query: Search query string.
        count: Number of results to return (1–10, default 5).
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
    Fetch a URL and return its readable text content.

    Use this tool after `web_search` when the search snippets are not detailed
    enough to answer the user's question and you need the full page content.

    Args:
        url: The full URL to fetch (must be http or https).
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