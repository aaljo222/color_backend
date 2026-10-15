"""Server-only, opt-in storage of non-identifying free-result demo fields."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def save_free_result_for_demo(result: dict) -> bool:
    """Return True only after Supabase confirms an insert; skip when disabled."""
    if os.environ.get("ASTRAL_SAVE_TEST_RESULTS") != "1":
        return False

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not url.startswith("https://") or not key:
        raise RuntimeError("Supabase test storage is enabled but server variables are missing")

    free = result["free_result"]
    row = {
        "day_master": free["day_master"],
        "day_pillar": free["day_pillar"],
        "color_name": free["color"]["name"],
        "color_hex": free["color"]["hex"],
        "engine_version": result["engine_version"],
    }
    request = Request(
        f"{url}/rest/v1/astral_test_results",
        data=json.dumps(row, ensure_ascii=False).encode("utf-8"),
        headers={
            "apikey": key,
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
            "User-Agent": "AstralColorDemo/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"Supabase insert returned HTTP {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"Supabase insert returned HTTP {exc.code}") from None
    except URLError:
        raise RuntimeError("Supabase insert connection failed") from None
    return True
