from urllib.parse import urlencode, urlparse, parse_qs, urlunsplit
from langchain.tools import tool

_UTM_SOURCE = "x"
_UTM_MEDIUM = "social"


@tool
def build_utm_url(base_url: str, campaign: str, content: str) -> str:
    """Build a UTM-tagged URL for an X post. source=x and medium=social are fixed."""
    parsed = urlparse(base_url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    existing.update({
        "utm_source": [_UTM_SOURCE],
        "utm_medium": [_UTM_MEDIUM],
        "utm_campaign": [campaign],
        "utm_content": [content],
    })
    query = urlencode({k: v[0] for k, v in existing.items()})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))
