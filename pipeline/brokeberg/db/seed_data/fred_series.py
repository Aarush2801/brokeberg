"""FRED series registered as EconomicIndicator entities. Observations land in `indicators`.

`aliases` are the common-usage names the entity linker sees in real text. Each alias must belong
to exactly one series: a shared exact alias makes the resolver return unresolved for everyone.
"""

from typing import NamedTuple

from brokeberg.taxonomy import Topic as T


class SeriesSeed(NamedTuple):
    series_id: str
    title: str
    frequency: str
    topic: T
    aliases: tuple[str, ...] = ()


SERIES: tuple[SeriesSeed, ...] = (
    SeriesSeed("CPIAUCSL", "Consumer Price Index for All Urban Consumers: All Items", "monthly",
               T.INFLATION_COST_OF_LIVING,
               ("CPI", "inflation", "consumer prices", "consumer price index", "headline CPI",
                "headline inflation", "CPI-U")),
    SeriesSeed("CPILFESL", "Core CPI: All Items Less Food and Energy", "monthly",
               T.INFLATION_COST_OF_LIVING,
               ("core CPI", "core inflation", "core consumer prices")),
    SeriesSeed("PCEPI", "Personal Consumption Expenditures Price Index", "monthly",
               T.INFLATION_COST_OF_LIVING,
               ("PCE", "PCE inflation", "PCE price index", "headline PCE")),
    SeriesSeed("PCEPILFE", "Core PCE Price Index: Excluding Food and Energy", "monthly",
               T.INFLATION_COST_OF_LIVING,
               ("core PCE", "core PCE inflation", "core PCE price index")),
    SeriesSeed("UNRATE", "Unemployment Rate", "monthly", T.LABOR_JOBS,
               ("unemployment", "jobless rate", "jobs")),
    SeriesSeed("PAYEMS", "All Employees, Total Nonfarm Payrolls", "monthly", T.LABOR_JOBS,
               ("payrolls", "jobs report", "nonfarm payrolls", "non-farm payrolls",
                "job growth", "jobs numbers")),
    SeriesSeed("CIVPART", "Labor Force Participation Rate", "monthly", T.LABOR_JOBS,
               ("labor force participation", "participation rate", "LFPR")),
    SeriesSeed("ICSA", "Initial Unemployment Claims", "weekly", T.LABOR_JOBS,
               ("jobless claims", "initial claims", "unemployment claims",
                "initial jobless claims", "weekly jobless claims")),
    SeriesSeed("DFF", "Federal Funds Effective Rate", "daily", T.MONETARY_POLICY,
               ("fed funds rate", "federal funds rate", "interest rates", "policy rate",
                "fed funds")),
    SeriesSeed("DGS10", "10-Year Treasury Constant Maturity Rate", "daily", T.MONETARY_POLICY,
               ("10-year", "10-year treasury", "treasury yield", "10-year yield",
                "10-year note", "ten-year treasury")),
    SeriesSeed("DGS2", "2-Year Treasury Constant Maturity Rate", "daily", T.MONETARY_POLICY,
               ("2-year", "2-year treasury", "2-year yield", "two-year treasury")),
    SeriesSeed("T10Y2Y", "10-Year Minus 2-Year Treasury Spread", "daily", T.MONETARY_POLICY,
               ("yield curve", "2s10s", "10s2s", "yield curve inversion", "inverted yield curve")),
    SeriesSeed("MORTGAGE30US", "30-Year Fixed Rate Mortgage Average", "weekly", T.HOUSING,
               ("mortgage rates", "mortgage rate", "30-year mortgage", "30-year fixed")),
    SeriesSeed("HOUST", "Housing Starts: Total New Privately Owned", "monthly", T.HOUSING,
               ("housing starts", "home construction", "new home construction")),
    SeriesSeed("CSUSHPINSA", "S&P CoreLogic Case-Shiller U.S. National Home Price Index",
               "monthly", T.HOUSING,
               ("Case-Shiller", "home prices", "house prices", "home price index")),
    SeriesSeed("GDPC1", "Real Gross Domestic Product", "quarterly", T.FISCAL_DEBT,
               ("GDP", "real GDP", "gross domestic product", "economic output")),
    SeriesSeed("A191RL1Q225SBEA", "Real GDP Growth Rate (annualized, q/q)", "quarterly",
               T.FISCAL_DEBT,
               ("GDP growth", "economic growth", "growth rate", "real GDP growth")),
    SeriesSeed("UMCSENT", "University of Michigan Consumer Sentiment", "monthly",
               T.INFLATION_COST_OF_LIVING,
               ("consumer sentiment", "Michigan sentiment", "consumer confidence",
                "UMich sentiment")),
    SeriesSeed("RSAFS", "Advance Retail Sales: Retail Trade and Food Services", "monthly",
               T.INFLATION_COST_OF_LIVING,
               ("retail sales", "consumer spending")),
    SeriesSeed("INDPRO", "Industrial Production: Total Index", "monthly", T.TRADE_TARIFFS,
               ("industrial production", "factory output", "manufacturing output")),
    SeriesSeed("GFDEBTN", "Federal Debt: Total Public Debt", "quarterly", T.FISCAL_DEBT,
               ("national debt", "federal debt", "public debt", "US debt")),
    SeriesSeed("FYFSD", "Federal Surplus or Deficit", "annual", T.FISCAL_DEBT,
               ("federal deficit", "budget deficit", "deficit")),
)
