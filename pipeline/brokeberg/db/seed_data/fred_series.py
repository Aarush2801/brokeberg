"""FRED series registered as EconomicIndicator entities. Observations land in `indicators`."""

from typing import NamedTuple

from brokeberg.taxonomy import Topic as T


class SeriesSeed(NamedTuple):
    series_id: str
    title: str
    frequency: str
    topic: T


SERIES: tuple[SeriesSeed, ...] = (
    SeriesSeed("CPIAUCSL", "Consumer Price Index for All Urban Consumers: All Items", "monthly",
               T.INFLATION_COST_OF_LIVING),
    SeriesSeed("CPILFESL", "Core CPI: All Items Less Food and Energy", "monthly",
               T.INFLATION_COST_OF_LIVING),
    SeriesSeed("PCEPI", "Personal Consumption Expenditures Price Index", "monthly",
               T.INFLATION_COST_OF_LIVING),
    SeriesSeed("PCEPILFE", "Core PCE Price Index: Excluding Food and Energy", "monthly",
               T.INFLATION_COST_OF_LIVING),
    SeriesSeed("UNRATE", "Unemployment Rate", "monthly", T.LABOR_JOBS),
    SeriesSeed("PAYEMS", "All Employees, Total Nonfarm Payrolls", "monthly", T.LABOR_JOBS),
    SeriesSeed("CIVPART", "Labor Force Participation Rate", "monthly", T.LABOR_JOBS),
    SeriesSeed("ICSA", "Initial Unemployment Claims", "weekly", T.LABOR_JOBS),
    SeriesSeed("DFF", "Federal Funds Effective Rate", "daily", T.MONETARY_POLICY),
    SeriesSeed("DGS10", "10-Year Treasury Constant Maturity Rate", "daily", T.MONETARY_POLICY),
    SeriesSeed("DGS2", "2-Year Treasury Constant Maturity Rate", "daily", T.MONETARY_POLICY),
    SeriesSeed("T10Y2Y", "10-Year Minus 2-Year Treasury Spread", "daily", T.MONETARY_POLICY),
    SeriesSeed("MORTGAGE30US", "30-Year Fixed Rate Mortgage Average", "weekly", T.HOUSING),
    SeriesSeed("HOUST", "Housing Starts: Total New Privately Owned", "monthly", T.HOUSING),
    SeriesSeed("CSUSHPINSA", "S&P CoreLogic Case-Shiller U.S. National Home Price Index",
               "monthly", T.HOUSING),
    SeriesSeed("GDPC1", "Real Gross Domestic Product", "quarterly", T.FISCAL_DEBT),
    SeriesSeed("A191RL1Q225SBEA", "Real GDP Growth Rate (annualized, q/q)", "quarterly",
               T.FISCAL_DEBT),
    SeriesSeed("UMCSENT", "University of Michigan Consumer Sentiment", "monthly",
               T.INFLATION_COST_OF_LIVING),
    SeriesSeed("RSAFS", "Advance Retail Sales: Retail Trade and Food Services", "monthly",
               T.INFLATION_COST_OF_LIVING),
    SeriesSeed("INDPRO", "Industrial Production: Total Index", "monthly", T.TRADE_TARIFFS),
    SeriesSeed("GFDEBTN", "Federal Debt: Total Public Debt", "quarterly", T.FISCAL_DEBT),
    SeriesSeed("FYFSD", "Federal Surplus or Deficit", "annual", T.FISCAL_DEBT),
)
