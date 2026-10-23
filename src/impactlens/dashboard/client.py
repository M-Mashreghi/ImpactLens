"""Thin API client used by the dashboard (any httpx.Client, incl. FastAPI's TestClient)."""

from __future__ import annotations

import os

import httpx


class ApiClientError(RuntimeError):
    pass


def make_client() -> httpx.Client:
    return httpx.Client(base_url=os.environ.get("IMPACTLENS_API_URL", "http://localhost:8000"), timeout=30)


class DashboardClient:
    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def _get(self, path: str, **params):
        response = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        if response.status_code >= 400:
            raise ApiClientError(response.json().get("error", {}).get("message", response.text))
        return response.json() if "json" in response.headers.get("content-type", "") else response.text

    def _post(self, path: str, body: dict):
        response = self.http.post(path, json=body)
        payload = response.json()
        if response.status_code >= 400:
            err = payload.get("error", {})
            raise ApiClientError(f"{err.get('message')}: {err.get('details')}")
        return payload

    def health(self):
        return self._get("/health")

    def ready(self):
        return self.http.get("/ready").json()

    def config(self):
        return self._get("/system/config")

    def portfolios(self):
        return self._get("/portfolios")

    def snapshot(self, snapshot_id):
        return self._get(f"/portfolio-snapshots/{snapshot_id}")

    def import_portfolio(self, name, csv_text, as_of=None):
        return self._post("/portfolios/import", {"name": name, "csv_text": csv_text, "as_of": as_of})

    def feed(self, snapshot_id=None, min_level=None, limit=100):
        return self._get("/impacts", snapshot_id=snapshot_id, min_level=min_level, limit=limit)

    def impact(self, impact_id):
        return self._get(f"/impacts/{impact_id}")

    def export(self, impact_id, fmt):
        return self._get(f"/impacts/{impact_id}/export", format=fmt)

    def news_list(self, limit=100):
        return self._get("/news", limit=limit)

    def news(self, news_id):
        return self._get(f"/news/{news_id}")

    def ingest(self, title, text, published_at=None):
        return self._post("/news", {"title": title, "text": text, "published_at": published_at})

    def alerts(self):
        return self._get("/alerts")

    def studies(self, news_id):
        return self._get("/research/event-studies", news_id=news_id)

    def run_studies(self, news_id):
        return self._post("/research/event-studies", {"news_id": news_id})

    def analogs(self, analysis_id):
        return self._get(f"/research/analogs/{analysis_id}")
