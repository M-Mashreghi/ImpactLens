"""Bounded HTTP GET with timeout, polite headers, size cap and limited retries."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str
    headers: dict[str, str]
    url: str


class HttpFetchError(RuntimeError):
    def __init__(self, error_type: str, message: str, status_code: int | None = None) -> None:
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(message)


def bounded_get(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_bytes: int = 5_000_000,
    retries: int = 2,
    backoff_seconds: float = 1.0,
    sleep=time.sleep,
) -> HttpResponse:
    if not url.lower().startswith(("http://", "https://")):
        raise HttpFetchError("InvalidUrl", "only http(s) URLs are supported")
    last: HttpFetchError | None = None
    for attempt in range(retries + 1):
        try:
            with client.stream("GET", url, headers=headers or {}, follow_redirects=True) as response:
                if response.status_code in RETRYABLE_STATUS:
                    last = HttpFetchError("HttpStatus", f"HTTP {response.status_code}", response.status_code)
                elif response.status_code == 304:
                    return HttpResponse(304, "", dict(response.headers), str(response.url))
                elif response.status_code >= 400:
                    raise HttpFetchError("HttpStatus", f"HTTP {response.status_code}", response.status_code)
                else:
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise HttpFetchError("TooLarge", f"response exceeds {max_bytes} bytes")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    encoding = response.encoding or "utf-8"
                    return HttpResponse(
                        response.status_code,
                        body.decode(encoding, errors="replace"),
                        dict(response.headers),
                        str(response.url),
                    )
        except httpx.TimeoutException:
            last = HttpFetchError("Timeout", "request timed out")
        except httpx.TransportError as exc:
            last = HttpFetchError("Transport", f"transport error: {type(exc).__name__}")
        if attempt < retries:
            sleep(backoff_seconds * (2**attempt))
    assert last is not None
    raise last
