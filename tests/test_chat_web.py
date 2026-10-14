import json
from urllib.parse import parse_qs, urlparse

from routers import chat_web


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_serpapi_search_returns_web_citation_fields(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _Response({
            "organic_results": [{
                "title": "Newton's second law",
                "snippet": "Force equals mass times acceleration.",
                "link": "https://example.test/newton",
            }],
        })

    monkeypatch.setenv("CHAT_WEB", "serpapi")
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(chat_web.urllib.request, "urlopen", fake_urlopen)

    results = chat_web.search_web("  Newton\u0000 second   law ")

    assert results == [{
        "title": "Newton's second law",
        "snippet": "Force equals mass times acceleration.",
        "url": "https://example.test/newton",
    }]
    params = parse_qs(urlparse(captured["url"]).query)
    assert params["engine"] == ["google"]
    assert params["q"] == ["Newton second law"]
    assert params["api_key"] == ["test-key"]
    assert captured["timeout"] == chat_web.DEFAULT_TIMEOUT_SECONDS


def test_missing_serpapi_key_disables_search(monkeypatch, caplog):
    monkeypatch.setenv("CHAT_WEB", "serpapi")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    assert chat_web.search_web("한국의 수도") == []
    assert "SERPAPI_API_KEY is not configured" in caplog.text


def test_off_provider_does_not_make_request(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("search must be disabled")

    monkeypatch.setenv("CHAT_WEB", "off")
    monkeypatch.setattr(chat_web.urllib.request, "urlopen", fail_urlopen)

    assert chat_web.search_web("한국의 수도") == []


def test_serpapi_failure_is_logged_and_returns_no_results(monkeypatch, caplog):
    def fail_urlopen(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setenv("CHAT_WEB", "serpapi")
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(chat_web.urllib.request, "urlopen", fail_urlopen)

    assert chat_web.search_web("한국의 수도") == []
    assert "SerpAPI search failed: TimeoutError" in caplog.text


def test_chat_web_citations_include_compatible_and_extended_fields(monkeypatch):
    from routers import chat_router

    monkeypatch.setattr(chat_router, "retrieve", lambda _query: [])
    monkeypatch.setattr(chat_router, "search_web", lambda _query: [{
        "title": "대한민국",
        "snippet": "대한민국의 수도는 서울특별시이다.",
        "url": "https://example.test/seoul",
    }])

    result = chat_router.run_agent("한국의 수도는 어디야?")

    assert result["source"] == "web"
    assert result["citations"] == [{
        "cite": "대한민국",
        "paper": "https://example.test/seoul",
        "text": "대한민국의 수도는 서울특별시이다.",
        "score": None,
        "url": "https://example.test/seoul",
        "kind": "web",
    }]
