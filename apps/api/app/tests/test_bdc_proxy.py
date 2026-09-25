"""Hosted BDC routing, safe failures and credential-free connectivity checks."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from app import bdc_preflight
from app.config import settings
from app.scrapers.base import BankPortalUnreachableError, ScraperUnavailableError
from app.scrapers.bdc_kony import BDCKonyScraper
from app.scrapers.bdc_proxy import get_bdc_proxy


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for name in ("server", "username", "password"):
        monkeypatch.setattr(settings, f"bdc_proxy_{name}", SecretStr(""))
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("RENDER", raising=False)


def configure_proxy(monkeypatch):
    monkeypatch.setattr(settings, "bdc_proxy_server", SecretStr("http://proxy.example:12321"))
    monkeypatch.setattr(settings, "bdc_proxy_username", SecretStr("proxy-user"))
    monkeypatch.setattr(settings, "bdc_proxy_password", SecretStr("proxy-secret_country-eg"))


def test_missing_proxy_never_falls_back_when_required():
    assert get_bdc_proxy() is None
    with pytest.raises(ScraperUnavailableError, match="Egyptian proxy"):
        get_bdc_proxy(required=True)


@pytest.mark.parametrize(
    "server",
    [
        "socks5://proxy.example:12321",
        "http://secret:password@proxy.example:12321",
        "http://proxy.example",
        "http://proxy.example:abc",
        "http://proxy.example:99999",
        "http://proxy.example:0",
        "http://proxy.example:80/path",
        "http://proxy.example:80?password=secret",
        "http://proxy.example:80#secret",
        "http://bad host:80",
        "http://[bad:80",
    ],
)
def test_invalid_proxy_is_rejected_without_echoing_secrets(monkeypatch, server):
    monkeypatch.setattr(settings, "bdc_proxy_server", SecretStr(server))
    with pytest.raises(ScraperUnavailableError) as caught:
        get_bdc_proxy()
    assert server not in str(caught.value)


@pytest.mark.parametrize("username,password", [("u", ""), ("", "p")])
def test_partial_auth_is_rejected(monkeypatch, username, password):
    monkeypatch.setattr(settings, "bdc_proxy_server", SecretStr("http://proxy.example:80"))
    monkeypatch.setattr(settings, "bdc_proxy_username", SecretStr(username))
    monkeypatch.setattr(settings, "bdc_proxy_password", SecretStr(password))
    with pytest.raises(ScraperUnavailableError):
        get_bdc_proxy()


def test_auth_without_server_never_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "bdc_proxy_password", SecretStr("secret"))
    with pytest.raises(ScraperUnavailableError):
        get_bdc_proxy()


def test_ip_authenticated_proxy(monkeypatch):
    monkeypatch.setattr(settings, "bdc_proxy_server", SecretStr("https://proxy.example:443"))
    assert get_bdc_proxy(required=True) == {"server": "https://proxy.example:443"}


def test_proxy_auth_does_not_appear_in_settings_repr(monkeypatch):
    configure_proxy(monkeypatch)
    assert "proxy-secret" not in repr(settings)
    assert "proxy-user" not in repr(settings)
    assert "proxy.example" not in repr(settings)


@pytest.fixture
def browser_mock(monkeypatch, tmp_path):
    import patchright.async_api

    import app.scrapers.bdc_kony as mod

    page = MagicMock()
    context = MagicMock(pages=[page], close=AsyncMock(), new_page=AsyncMock(return_value=page))
    runtime = MagicMock(stop=AsyncMock())
    runtime.chromium.launch_persistent_context = AsyncMock(return_value=context)
    manager = MagicMock(start=AsyncMock(return_value=runtime))
    monkeypatch.setattr(patchright.async_api, "async_playwright", lambda: manager)
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda **_: str(profile))
    return runtime, context, page, profile


@pytest.mark.asyncio
async def test_hosted_launch_routes_entire_browser_through_proxy(monkeypatch, browser_mock):
    configure_proxy(monkeypatch)
    monkeypatch.setattr(settings, "app_env", "production")
    runtime, context, page, profile = browser_mock
    scraper = BDCKonyScraper("bank-user", "bank-password")
    assert await scraper._launch_browser() == (context, context, page)
    options = runtime.chromium.launch_persistent_context.call_args.kwargs
    assert options["proxy"] == get_bdc_proxy(required=True)
    assert "bypass" not in options["proxy"]
    assert not options.get("ignore_https_errors")
    await scraper._close_browser(context)
    runtime.stop.assert_awaited_once()
    assert not profile.exists()


@pytest.mark.asyncio
async def test_local_launch_retains_direct_connection(browser_mock):
    runtime, context, _, _ = browser_mock
    scraper = BDCKonyScraper("u", "p")
    await scraper._launch_browser()
    assert "proxy" not in runtime.chromium.launch_persistent_context.call_args.kwargs
    await scraper._close_browser(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", ["settings", "render"])
async def test_hosted_signals_require_proxy_before_browser_start(monkeypatch, browser_mock, signal):
    if signal == "settings":
        monkeypatch.setattr(settings, "app_env", "production")
    else:
        monkeypatch.setenv("RENDER", "true")
    runtime, _, _, _ = browser_mock
    with pytest.raises(ScraperUnavailableError):
        await BDCKonyScraper("u", "p")._launch_browser()
    runtime.chromium.launch_persistent_context.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_launch_failure_cleans_up_without_exposing_proxy(
    monkeypatch, browser_mock, cancelled
):
    configure_proxy(monkeypatch)
    runtime, _, _, profile = browser_mock
    runtime.chromium.launch_persistent_context.side_effect = (
        asyncio.CancelledError() if cancelled else RuntimeError("proxy-secret_country-eg")
    )
    with pytest.raises(asyncio.CancelledError if cancelled else ScraperUnavailableError) as caught:
        await BDCKonyScraper("u", "p")._launch_browser()
    assert "proxy-secret" not in str(caught.value)
    runtime.stop.assert_awaited_once()
    assert not profile.exists()


@pytest.mark.asyncio
async def test_proxy_navigation_error_is_actionable_and_does_not_submit_login():
    from patchright.async_api import Error

    page = MagicMock(goto=AsyncMock(side_effect=Error("secret ERR_TUNNEL_CONNECTION_FAILED")))
    with pytest.raises(BankPortalUnreachableError, match="proxy connection") as caught:
        await BDCKonyScraper("u", "p")._login_and_capture_auth(page)
    assert "secret" not in str(caught.value)
    page.fill.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("trace", ["loc=US\nip=192.0.2.1", "loc=EG\nip=bad", "blocked"])
async def test_preflight_rejects_unconfirmed_egyptian_exit(trace):
    response = MagicMock(status=200, text=AsyncMock(return_value=trace))
    page = MagicMock(goto=AsyncMock(return_value=response))
    with pytest.raises(bdc_preflight.PreflightError):
        await bdc_preflight._check_egress(page)


@pytest.mark.asyncio
async def test_preflight_reads_egyptian_ip_without_printing_it(capsys):
    response = MagicMock(status=200, text=AsyncMock(return_value="loc=EG\nip=192.0.2.1"))
    page = MagicMock(goto=AsyncMock(return_value=response))
    assert await bdc_preflight._check_egress(page) == "192.0.2.1"
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, MagicMock(status=429)])
async def test_preflight_rejects_failed_location_probe(response):
    page = MagicMock(goto=AsyncMock(return_value=response))
    with pytest.raises(bdc_preflight.PreflightError, match="location check failed"):
        await bdc_preflight._check_egress(page)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "rotation", "no_form", "blocked", "geo"])
async def test_preflight_checks_form_and_ip_without_bank_login(monkeypatch, failure):
    configure_proxy(monkeypatch)
    page = MagicMock(
        goto=AsyncMock(return_value=MagicMock(status=403 if failure == "blocked" else 200))
    )
    page.wait_for_timeout = AsyncMock()
    frame = MagicMock(url="https://bdconline.com.eg/LoginPage.html")
    frame.locator.return_value.is_visible = AsyncMock(return_value=failure != "no_form")
    page.frames = [frame]
    context = MagicMock(new_page=AsyncMock(return_value=page))
    launch = AsyncMock(return_value=(context, context, page))
    close = AsyncMock()
    monkeypatch.setattr(BDCKonyScraper, "_launch_browser", launch)
    monkeypatch.setattr(BDCKonyScraper, "_close_browser", close)
    monkeypatch.setattr(
        bdc_preflight,
        "_check_egress",
        AsyncMock(
            side_effect=(
                bdc_preflight.PreflightError("location unavailable")
                if failure == "geo"
                else ["192.0.2.1", "192.0.2.2" if failure == "rotation" else "192.0.2.1"]
            )
        ),
    )
    if failure:
        with pytest.raises(bdc_preflight.PreflightError):
            await bdc_preflight.check_connectivity()
    else:
        await bdc_preflight.check_connectivity()
    close.assert_awaited_once_with(context)
    page.fill.assert_not_called()
    frame.fill.assert_not_called()
    frame.click.assert_not_called()


def test_preflight_cli_sanitizes_unexpected_failures(monkeypatch, capsys):
    monkeypatch.setattr(
        bdc_preflight, "check_connectivity", AsyncMock(side_effect=ValueError("secret"))
    )
    assert bdc_preflight.main() == 1
    assert "secret" not in capsys.readouterr().out


def test_preflight_cli_reports_missing_config(capsys):
    assert bdc_preflight.main() == 1
    assert "Configure BDC_PROXY_SERVER" in capsys.readouterr().out


def test_preflight_cli_success(monkeypatch):
    monkeypatch.setattr(bdc_preflight, "check_connectivity", AsyncMock())
    assert bdc_preflight.main() == 0
