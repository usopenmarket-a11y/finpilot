# Bank scraper modules — one module per supported bank (NBE, CIB, BDC, UB).
# Each scraper is responsible for logging in, navigating, and extracting
# raw transaction/balance data using Playwright (with BeautifulSoup4 fallback).

from app.scrapers.base import (
    BankScraper,
    BankPortalUnreachableError,
    ScraperException,
    ScraperLoginError,
    ScraperOTPRequired,
    ScraperParseError,
    ScraperResult,
    ScraperTimeoutError,
)
from app.scrapers.cib import CIBScraper
from app.scrapers.nbe import NBEScraper

__all__ = [
    # Base abstractions
    "BankScraper",
    "ScraperResult",
    # Exceptions
    "ScraperException",
    "ScraperLoginError",
    "ScraperTimeoutError",
    "ScraperParseError",
    "ScraperOTPRequired",
    "BankPortalUnreachableError",
    # Bank scrapers
    "NBEScraper",
    "CIBScraper",
]
