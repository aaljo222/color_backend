"""Optional SerpAPI-backed Google search for chatbot fallback."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)
SERPAPI_URL = "https://serpapi.com/search.json"
DEFAULT_TIMEOUT_SECONDS = 8
MAX_RESULTS = 3


def _clean_query(query: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", query)).strip()[:300]


def _serpapi_search(query: str) -> list[dict[str, str]]:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        logger.warning("Chat web search disabled: SERPAPI_API_KEY is not configured")
        return []

    params = urllib.parse.urlencode({
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "hl": "ko",
        "gl": "kr",
    })
    request = urllib.request.Request(
        f"{SERPAPI_URL}?{params}",
        headers={"User-Agent": "MaC-Chat/1.0"},
    )
    try:
        timeout_setting = float(os.getenv("CHAT_WEB_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
        timeout = max(6.0, min(10.0, timeout_setting))
    except ValueError:
        logger.error("Invalid CHAT_WEB_TIMEOUT; using %s seconds", DEFAULT_TIMEOUT_SECONDS)
        timeout = DEFAULT_TIMEOUT_SECONDS

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("SerpAPI search failed with HTTP %s", exc.code)
        return []
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("SerpAPI search failed: %s", type(exc).__name__)
        return []

    if not isinstance(payload, dict):
        logger.warning("SerpAPI returned an invalid response")
        return []
    if payload.get("error"):
        logger.warning("SerpAPI returned an error response")
        return []

    results = []
    organic_results = payload.get("organic_results", [])
    if not isinstance(organic_results, list):
        logger.warning("SerpAPI returned invalid organic results")
        return []
    for item in organic_results[:MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        url = str(item.get("link") or "").strip()
        if not title or not snippet or not url.startswith(("https://", "http://")):
            continue
        results.append({"title": title, "snippet": snippet, "url": url})
    return results


def _wikipedia_search(query: str) -> list[dict[str, str]]:
    """Legacy provider kept available for deployments that explicitly select it."""
    params = urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": 1,
        "srlimit": MAX_RESULTS,
    })
    request = urllib.request.Request(
        f"https://ko.wikipedia.org/w/api.php?{params}",
        headers={"User-Agent": "MaC-Chat/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("Wikipedia search failed with HTTP %s", exc.code)
        return []
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Wikipedia search failed: %s", type(exc).__name__)
        return []

    if not isinstance(payload, dict):
        logger.warning("Wikipedia returned an invalid response")
        return []
    query_data = payload.get("query", {})
    if not isinstance(query_data, dict) or not isinstance(query_data.get("search", []), list):
        logger.warning("Wikipedia returned invalid search results")
        return []

    results = []
    for item in query_data.get("search", [])[:MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        results.append({
            "title": title,
            "snippet": re.sub(r"<[^>]+>", "", str(item.get("snippet") or "")),
            "url": "https://ko.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
        })
    return results


def search_web(query: str) -> list[dict[str, str]]:
    """Search with the configured provider; missing credentials and failures return no results."""
    cleaned = _clean_query(query)
    if not cleaned:
        return []

    provider = os.getenv("CHAT_WEB", "serpapi").strip().lower()
    if provider == "off":
        return []
    if provider == "serpapi":
        return _serpapi_search(cleaned)
    if provider == "wikipedia":
        return _wikipedia_search(cleaned)
    logger.error("Unsupported CHAT_WEB provider: %s", provider)
    return []
