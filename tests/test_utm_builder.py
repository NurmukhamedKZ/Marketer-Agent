from app.tools.utm_builder import build_utm_url


def test_build_utm_url_contains_fixed_params():
    result = build_utm_url.invoke({
        "base_url": "https://example.com",
        "campaign": "saas-launch",
        "content": "pain-point",
    })
    assert "utm_source=x" in result
    assert "utm_medium=social" in result


def test_build_utm_url_contains_agent_params():
    result = build_utm_url.invoke({
        "base_url": "https://example.com",
        "campaign": "saas-launch",
        "content": "pain-point",
    })
    assert "utm_campaign=saas-launch" in result
    assert "utm_content=pain-point" in result


def test_build_utm_url_base_url_preserved():
    result = build_utm_url.invoke({
        "base_url": "https://myapp.io/landing",
        "campaign": "q1",
        "content": "angle",
    })
    assert result.startswith("https://myapp.io/landing")


def test_build_utm_url_existing_query_params_preserved():
    result = build_utm_url.invoke({
        "base_url": "https://example.com?ref=header",
        "campaign": "launch",
        "content": "cta",
    })
    assert "ref=header" in result
    assert "utm_source=x" in result
