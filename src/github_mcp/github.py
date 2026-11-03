"""Bounded, read-only access to the fixed GitHub API origin."""

import json
import math
import os
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime

import requests

API = "https://api.github.com"
TIMEOUT = (3.05, 10)
ATTEMPTS = 3
MAX_WAIT = 5


def _rate_delay(headers: Mapping[str, str]) -> int:
    delays = []
    retry = headers.get("Retry-After")
    if retry:
        try:
            seconds = float(retry)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(retry).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                seconds = math.nan
        if math.isfinite(seconds):
            delays.append(max(0, math.ceil(seconds)))
    if headers.get("X-RateLimit-Remaining") == "0":
        try:
            seconds = float(headers["X-RateLimit-Reset"]) - time.time()
            if math.isfinite(seconds):
                delays.append(max(0, math.ceil(seconds)))
        except (KeyError, ValueError, OverflowError):
            pass
    return max(delays) if delays else 60


class _ResponseTooLarge(ValueError):
    pass


def _json(res: requests.Response, max_bytes: int | None):
    if max_bytes is None:
        return res.json()
    body = bytearray()
    for chunk in res.iter_content(chunk_size=min(max_bytes + 1, 65536)):
        if len(body) + len(chunk) > max_bytes:
            raise _ResponseTooLarge
        body.extend(chunk)
    return json.loads(body)


def gh(
    path: str, params: dict | None = None, *, max_bytes: int | None = None
) -> dict | list:
    """Return JSON or a sanitized error; never retry a long rate-limit wait."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN", "").strip():
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(ATTEMPTS):
        delay = 2**attempt
        retryable = False
        try:
            # Do not forward credentials or follow server-supplied external URLs.
            with requests.get(
                f"{API}{path}",
                headers=headers,
                params=params,
                timeout=TIMEOUT,
                allow_redirects=False,
                stream=max_bytes is not None,
            ) as res:
                if res.status_code == 200:
                    try:
                        data = _json(res, max_bytes)
                    except _ResponseTooLarge:
                        raise
                    except (ValueError, RecursionError):
                        data = None
                    if isinstance(data, (dict, list)):
                        return data
                    return {
                        "error": "Invalid GitHub JSON response",
                        "error_code": "MALFORMED_RESPONSE",
                    }
                secondary = False
                if res.status_code == 403:
                    try:
                        data = _json(res, max_bytes)
                        secondary = (
                            isinstance(data, dict)
                            and "secondary rate limit"
                            in str(data.get("message", "")).lower()
                        )
                    except _ResponseTooLarge:
                        raise
                    except (ValueError, RecursionError):
                        pass
                if res.status_code == 429 or (
                    res.status_code == 403
                    and (
                        "Retry-After" in res.headers
                        or res.headers.get("X-RateLimit-Remaining") == "0"
                        or secondary
                    )
                ):
                    delay = _rate_delay(res.headers)
                    error = {
                        "error": f"GitHub rate limited; retry in {delay} seconds",
                        "error_code": "RATE_LIMITED",
                        "retry_after_seconds": delay,
                    }
                    retryable = delay <= MAX_WAIT
                else:
                    code, message = {
                        401: ("AUTHENTICATION", "Invalid or missing GITHUB_TOKEN"),
                        403: (
                            "FORBIDDEN",
                            "GitHub access denied; check token permissions",
                        ),
                        404: ("NOT_FOUND", "Not found"),
                        422: (
                            "VALIDATION",
                            "GitHub rejected the request; check query and page limits",
                        ),
                    }.get(
                        res.status_code,
                        ("HTTP_ERROR", f"GitHub API error: {res.status_code}"),
                    )
                    if 300 <= res.status_code < 400:
                        code, message = (
                            "REDIRECT",
                            "GitHub redirected the request; use the canonical repository name",
                        )
                    error = {"error": message, "error_code": code}
                    retryable = res.status_code in (500, 502, 503, 504)
                    if retryable and "Retry-After" in res.headers:
                        delay = _rate_delay(res.headers)
                        error["retry_after_seconds"] = delay
                        error["error"] = f"{message}; retry in {delay} seconds"
                        retryable = delay <= MAX_WAIT
        except _ResponseTooLarge:
            return {
                "error": "GitHub response exceeds the download limit",
                "error_code": "RESPONSE_TOO_LARGE",
            }
        except requests.exceptions.SSLError:
            return {
                "error": "GitHub TLS verification failed",
                "error_code": "TLS_ERROR",
            }
        except (requests.Timeout, requests.ConnectionError) as exc:
            code = "TIMEOUT" if isinstance(exc, requests.Timeout) else "NETWORK_ERROR"
            error = {
                "error": "GitHub request timed out"
                if code == "TIMEOUT"
                else "GitHub connection failed",
                "error_code": code,
            }
            retryable = True
        except requests.RequestException:
            return {"error": "GitHub request failed", "error_code": "NETWORK_ERROR"}
        if not retryable or attempt == ATTEMPTS - 1:
            return error
        time.sleep(delay)
    raise AssertionError("Unreachable request state")
