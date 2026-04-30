"""Unit tests for MCP web_search server tools (app/mcp/web_search.py)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.web_search import (
    _normalize,
    _strip_tags,
    _validate_url,
    web_fetch,
    web_search,
)


# ── Helper functions ───────────────────────────────────────────────────────────


def test_strip_tags_removes_html():
    assert _strip_tags("<p>Hello <b>World</b></p>") == "Hello World"


def test_strip_tags_removes_script():
    assert _strip_tags("<script>alert(1)</script>text") == "text"


def test_strip_tags_removes_style():
    assert _strip_tags("<style>.foo{color:red}</style>text") == "text"


def test_strip_tags_unescapes_entities():
    assert _strip_tags("AT&amp;T &lt;br&gt;") == "AT&T <br>"


def test_normalize_collapses_spaces():
    assert _normalize("hello   world") == "hello world"


def test_normalize_collapses_blank_lines():
    result = _normalize("a\n\n\n\nb")
    assert "\n\n\n" not in result
    assert "a" in result and "b" in result


def test_validate_url_accepts_http():
    ok, msg = _validate_url("http://example.com")
    assert ok is True
    assert msg == ""


def test_validate_url_accepts_https():
    ok, _ = _validate_url("https://example.com/path?q=1")
    assert ok is True


def test_validate_url_rejects_ftp():
    ok, msg = _validate_url("ftp://example.com")
    assert ok is False
    assert "http" in msg.lower() or "ftp" in msg


def test_validate_url_rejects_missing_domain():
    ok, msg = _validate_url("https://")
    assert ok is False
    assert "domain" in msg.lower()


# ── web_search tool ────────────────────────────────────────────────────────────


def _make_httpx_client_mock(json_response: dict) -> MagicMock:
    """Build an AsyncMock httpx.AsyncClient that returns json_response."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = json_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_web_search_returns_formatted_results():
    payload = {
        "results": [
            {"title": "SaaS Tips", "url": "https://saas.io/tips", "content": "10 tips"},
            {"title": "Startup Guide", "url": "https://guide.io", "content": "Guide snippet"},
        ]
    }
    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=_make_httpx_client_mock(payload)):
        result = await web_search("saas tips", count=2)

    assert "SaaS Tips" in result
    assert "https://saas.io/tips" in result
    assert "10 tips" in result
    assert "Startup Guide" in result


@pytest.mark.asyncio
async def test_web_search_no_results():
    payload = {"results": []}
    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=_make_httpx_client_mock(payload)):
        result = await web_search("obscure query with no results")

    assert "No results found" in result


@pytest.mark.asyncio
async def test_web_search_http_error_returns_error_string():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=mock_client):
        result = await web_search("any query")

    assert result.startswith("❌")
    assert "connection refused" in result


@pytest.mark.asyncio
async def test_web_search_count_is_capped_at_20():
    """Requesting more than 20 results returns at most 20."""
    items = [{"title": f"T{i}", "url": f"https://x.com/{i}", "content": ""} for i in range(30)]
    payload = {"results": items}

    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=_make_httpx_client_mock(payload)):
        result = await web_search("broad query", count=50)

    # 20 results → titles T0…T19 present, T20 absent
    assert "T19" in result
    assert "T20" not in result


@pytest.mark.asyncio
async def test_web_search_count_minimum_is_1():
    payload = {"results": [{"title": "Only", "url": "https://x.com", "content": ""}]}
    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=_make_httpx_client_mock(payload)):
        result = await web_search("query", count=0)  # 0 → capped to 1

    assert "Only" in result


# ── web_fetch tool ─────────────────────────────────────────────────────────────


def _make_fetch_mock(content: str, content_type: str = "text/plain", status_code: int = 200) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = content
    mock_response.headers = {"content-type": content_type}
    mock_response.json.return_value = {}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_web_fetch_returns_plain_text():
    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=_make_fetch_mock("Hello world")):
        result = await web_fetch("https://example.com")

    assert "Hello world" in result


@pytest.mark.asyncio
async def test_web_fetch_strips_html_tags():
    html = "<html><body><p>Clean <b>content</b></p></body></html>"
    with patch(
        "app.mcp.web_search.httpx.AsyncClient",
        return_value=_make_fetch_mock(html, content_type="text/html"),
    ):
        result = await web_fetch("https://example.com")

    assert "<b>" not in result
    assert "Clean" in result
    assert "content" in result


@pytest.mark.asyncio
async def test_web_fetch_truncates_at_15000_chars():
    long_text = "x" * 20_000
    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=_make_fetch_mock(long_text)):
        result = await web_fetch("https://example.com")

    assert "Truncated" in result
    assert len(result) < 16_000  # 15000 chars + short suffix


@pytest.mark.asyncio
async def test_web_fetch_no_truncation_label_for_short_content():
    short_text = "Short page content."
    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=_make_fetch_mock(short_text)):
        result = await web_fetch("https://example.com")

    assert "Truncated" not in result


@pytest.mark.asyncio
async def test_web_fetch_invalid_scheme_returns_error():
    result = await web_fetch("ftp://example.com/file.txt")
    assert result.startswith("❌")
    assert "ftp" in result.lower() or "http" in result.lower()


@pytest.mark.asyncio
async def test_web_fetch_missing_domain_returns_error():
    result = await web_fetch("https://")
    assert result.startswith("❌")


@pytest.mark.asyncio
async def test_web_fetch_http_error_returns_error_string():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))

    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=mock_client):
        result = await web_fetch("https://example.com")

    assert result.startswith("❌")
    assert "timeout" in result


@pytest.mark.asyncio
async def test_web_fetch_json_content_type_returns_json():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = '{"key": "value"}'
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"key": "value"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("app.mcp.web_search.httpx.AsyncClient", return_value=mock_client):
        result = await web_fetch("https://api.example.com/data")

    assert '"key"' in result
    assert '"value"' in result
