import httpx
import respx

from app.pipeline.links import allowed_domains, domain_allowed, link_status


def test_allowed_domains_strip_www() -> None:
    assert allowed_domains(["https://www.BleepingComputer.com/news/x", "https://github.com/a/b"]) == {
        "bleepingcomputer.com",
        "github.com",
    }


def test_domain_allowed_subdomains_only() -> None:
    allowed = {"bleepingcomputer.com"}
    assert domain_allowed("https://www.bleepingcomputer.com/x", allowed)
    assert domain_allowed("https://news.bleepingcomputer.com/x", allowed)
    assert not domain_allowed("https://evil-bleepingcomputer.com/x", allowed)
    assert not domain_allowed("https://bleepingcomputer.com.evil.io/x", allowed)
    assert not domain_allowed("javascript:alert(1)", allowed)


@respx.mock
async def test_link_alive_follows_redirect() -> None:
    respx.head("https://a.com/old").mock(
        return_value=httpx.Response(301, headers={"location": "https://a.com/new"})
    )
    respx.head("https://a.com/new").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient(follow_redirects=True) as http:
        assert await link_status(http, "https://a.com/old") == "ok"


@respx.mock
async def test_link_dead_404() -> None:
    respx.head("https://a.com/x").mock(return_value=httpx.Response(404))
    respx.get("https://a.com/x").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient(follow_redirects=True) as http:
        assert await link_status(http, "https://a.com/x") == "dead"


@respx.mock
async def test_head_not_allowed_falls_back_to_get() -> None:
    respx.head("https://a.com/x").mock(return_value=httpx.Response(405))
    respx.get("https://a.com/x").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient(follow_redirects=True) as http:
        assert await link_status(http, "https://a.com/x") == "ok"


@respx.mock
async def test_bot_blocked_is_unknown_not_dead() -> None:
    respx.head("https://a.com/x").mock(return_value=httpx.Response(403))
    respx.get("https://a.com/x").mock(return_value=httpx.Response(403))
    async with httpx.AsyncClient(follow_redirects=True) as http:
        assert await link_status(http, "https://a.com/x") == "unknown"


@respx.mock
async def test_network_error_is_unknown() -> None:
    respx.head("https://a.com/x").mock(side_effect=httpx.ConnectTimeout("t"))
    respx.get("https://a.com/x").mock(side_effect=httpx.ConnectTimeout("t"))
    async with httpx.AsyncClient(follow_redirects=True) as http:
        assert await link_status(http, "https://a.com/x") == "unknown"
