"""The world stock universe: country and region index ETFs listed in the
US (the one market whose prices Nasdaq's public API serves), and the
largest US companies.

`LARGE_CAPS` is a recent S&P 100 list. It is today's list, so it holds
the companies that grew into the top 100 and none that fell out of it:
anything measured on it absolute terms is flattered (survivorship). A
comparison inside it — a model's picks against holding all of them — is
fairer, since both sides share the bias.
"""
from __future__ import annotations

WORLD_ETFS: dict[str, str] = {
    "SPY": "US large caps (S&P 500)", "QQQ": "US tech (Nasdaq 100)",
    "IWM": "US small caps (Russell 2000)", "DIA": "US Dow 30",
    "ACWI": "world (MSCI ACWI)", "VT": "world, total market", "EFA": "developed ex-US",
    "EEM": "emerging markets", "VGK": "Europe", "EWU": "United Kingdom", "EWG": "Germany",
    "EWQ": "France", "EWJ": "Japan", "EWA": "Australia", "EWC": "Canada", "EWZ": "Brazil",
    "EWW": "Mexico", "FXI": "China large caps", "INDA": "India", "EWY": "South Korea",
    "EWT": "Taiwan", "EWH": "Hong Kong", "EWS": "Singapore", "EZA": "South Africa",
    "TLT": "US Treasuries 20y+", "IEF": "US Treasuries 7-10y", "GLD": "gold",
}

LARGE_CAPS: list[str] = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN", "AVGO", "AXP",
    "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "C", "CAT", "CHTR", "CL", "CMCSA", "COF", "COP",
    "COST", "CRM", "CSCO", "CVS", "CVX", "DE", "DHR", "DIS", "DUK", "EMR", "F", "FDX", "GD",
    "GE", "GILD", "GM", "GOOGL", "GS", "HD", "HON", "IBM", "INTC", "INTU", "ISRG", "JNJ",
    "JPM", "KO", "LIN", "LLY", "LMT", "LOW", "MA", "MCD", "MDLZ", "MDT", "MET", "META", "MMM",
    "MO", "MRK", "MS", "MSFT", "NEE", "NFLX", "NKE", "NOW", "NVDA", "ORCL", "PEP", "PFE", "PG",
    "PLTR", "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T", "TGT", "TMO",
    "TMUS", "TSLA", "TXN", "UBER", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT", "XOM",
]


def asset_class(ticker: str) -> str:
    return "etf" if ticker in WORLD_ETFS else "stocks"
