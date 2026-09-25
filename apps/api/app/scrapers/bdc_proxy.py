"""Validate server-side BDC proxy settings without exposing credentials."""

from urllib.parse import urlsplit

from app.config import settings
from app.scrapers.base import ScraperUnavailableError


def get_bdc_proxy(*, required: bool = False) -> dict[str, str] | None:
    """Return Chromium's HTTP proxy options, with no direct fallback on error.

    Country and sticky-session selection belong in the provider's generated
    credentials. Keeping these opaque supports switching providers after a
    connectivity test without changing the scraper.
    """
    server = settings.bdc_proxy_server.get_secret_value().strip()
    username = settings.bdc_proxy_username.get_secret_value()
    password = settings.bdc_proxy_password.get_secret_value()
    if not server:
        if required or username or password:
            raise ScraperUnavailableError(
                "BDC cloud sync needs an Egyptian proxy. Configure BDC_PROXY_SERVER, "
                "BDC_PROXY_USERNAME and BDC_PROXY_PASSWORD on the backend.",
                bank_code="BDC_RETAIL",
            )
        return None

    try:
        parsed = urlsplit(server)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.port is not None
            and parsed.port > 0
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and not any(ch.isspace() for ch in server)
        )
    except ValueError:
        valid = False
    if not valid or bool(username) != bool(password):
        raise ScraperUnavailableError(
            "BDC proxy configuration is invalid. Use an HTTP(S) server URL with "
            "an explicit port and keep the proxy username/password in their "
            "separate environment variables (both set, or both empty for IP authentication).",
            bank_code="BDC_RETAIL",
        )

    proxy = {"server": server}
    if username:
        proxy.update(username=username, password=password)
    return proxy
