"""NVD CVE API 2.0: oxirgi 24 soatdagi kritik zaifliklar."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.collectors.base import FetchContext, RawItem
from app.db.models import Source

_FMT = "%Y-%m-%dT%H:%M:%S.000"


def _cvss(metrics: dict[str, Any]) -> tuple[float | None, str | None]:
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30"):
        for m in metrics.get(key) or []:
            data = m.get("cvssData") or {}
            if "baseScore" in data:
                return float(data["baseScore"]), data.get("baseSeverity")
    return None, None


def parse(content: bytes, source: Source, fctx: FetchContext) -> list[RawItem]:
    data = json.loads(content)
    items: list[RawItem] = []
    for v in data.get("vulnerabilities", [])[:50]:
        cve = v.get("cve") or {}
        cve_id = cve.get("id")
        if not cve_id:
            continue
        desc = next((d.get("value", "") for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")
        score, severity = _cvss(cve.get("metrics") or {})
        published = None
        if cve.get("published"):
            try:
                published = datetime.fromisoformat(cve["published"]).replace(tzinfo=UTC)
            except ValueError:
                published = None
        items.append(
            RawItem(
                url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                title=f"{cve_id}: {desc[:160]}".strip(),
                summary=f"{desc[:1200]} CVSS: {score} ({severity}).",
                published_at=published,
                lang="en",
                extra={"cve": cve_id, "cvss": score, "severity": severity},
            )
        )
    return items


async def fetch(http: httpx.AsyncClient, source: Source, fctx: FetchContext) -> list[RawItem]:
    start = fctx.now.astimezone(UTC) - timedelta(hours=24)
    params = {
        "pubStartDate": start.strftime(_FMT),
        "pubEndDate": fctx.now.astimezone(UTC).strftime(_FMT),
        "cvssV3Severity": "CRITICAL",
        "resultsPerPage": "50",
    }
    headers = {"apiKey": fctx.nvd_api_key} if fctx.nvd_api_key else {}
    r = await http.get(source.url, params=params, headers=headers)
    r.raise_for_status()
    return parse(r.content, source, fctx)
