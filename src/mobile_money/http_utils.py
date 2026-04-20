from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class HttpRequestError(RuntimeError):
    pass


def request_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 10) -> dict[str, Any]:
    body = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise HttpRequestError(f"HTTP {exc.code} {method} {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HttpRequestError(f"Connection failed for {method} {url}: {exc.reason}") from exc
