"""URL'ni kanonik ko'rinishga keltirish va xeshlash."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "yclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "igshid",
        "_hsenc",
        "_hsmi",
        "mkt_tok",
        "cmpid",
        "ncid",
        "guccounter",
        "guce_referrer",
        "guce_referrer_sig",
        "sr_share",
        "spm",
        "utm",
    }
)
_DEFAULT_PORTS = {"http": ":80", "https": ":443"}


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    port = _DEFAULT_PORTS.get(scheme)
    if port and host.endswith(port):
        host = host[: -len(port)]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:40]


def domain_of(url: str) -> str:
    host = urlsplit(url.strip()).netloc.lower().split("@")[-1].split(":")[0]
    return host.removeprefix("www.")
