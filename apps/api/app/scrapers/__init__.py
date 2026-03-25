# Bank scraper modules — one module per supported bank (NBE, CIB, BDC, UB).
# Each scraper is responsible for logging in, navigating, and extracting
# raw transaction/balance data using Playwright (with BeautifulSoup4 fallback).

from app.scrapers.base import (
    BankPortalUnreachableError,
    BankScraper,
    ScraperException,
    ScraperLoginError,
    ScraperOTPRequired,
    ScraperParseError,
    ScraperPasswordChangeRequired,
    ScraperResult,
    ScraperTimeoutError,
)
from app.scrapers.bdc import BDCScraper
from app.scrapers.bdc_retail import BDCRetailScraper
from app.scrapers.cib import CIBScraper
from app.scrapers.nbe import NBEScraper
from app.scrapers.ub import UBScraper

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
    "ScraperPasswordChangeRequired",
    "BankPortalUnreachableError",
    # Bank scrapers
    "NBEScraper",
    "CIBScraper",
    "BDCScraper",
    "BDCRetailScraper",
    "UBScraper",
]
