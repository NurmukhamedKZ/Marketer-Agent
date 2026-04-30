from urllib.parse import urlencode, urlparse, parse_qs, urlunsplit
from langchain.tools import tool

_UTM_SOURCE = "x"
_UTM_MEDIUM = "social"


@tool
def build_utm_url(base_url: str, campaign: str, content: str) -> str:
    """Build a UTM-tagged tracking URL for an X post. utm_source=x and
    utm_medium=social are fixed — only campaign and content are caller-controlled.
    Call this BEFORE create_post_draft and embed the returned URL in the draft.

    Args:
        base_url: The product landing URL to tag. Must be a full http(s) URL.
            Example: "https://example.com/pricing".
            Existing query params are preserved; existing utm_* params are overwritten.
        campaign: Kebab-case campaign slug, max 30 chars, [a-z0-9-] only.
            Group posts that share a strategic theme.
            Good: "agents-replace-sdr", "launch-week-2026"
            Bad:  "Agents Replace SDR" (spaces, caps), "campaign_1" (underscores)
        content: Per-post identifier for splitting CTR within a campaign.
            Recommended: short slug derived from the post angle, max 40 chars.
            Example: "hook-a", "founder-take", "stat-thread".

    Returns:
        Full URL string with utm_source=x, utm_medium=social, utm_campaign,
        utm_content appended. Example:
        "https://example.com/pricing?utm_source=x&utm_medium=social&utm_campaign=agents-replace-sdr&utm_content=hook-a"

    Edge cases:
        - URL fragments (#section) are preserved.
        - Does NOT validate that base_url is reachable; only parses syntax.
        - If base_url already has utm_source/medium/campaign/content, they are
          replaced (not duplicated).
    """
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
