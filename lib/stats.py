import math
import numpy as np
import pandas as pd
import scipy.stats as st

def prob_cone(stock_price: float, volatility: float, days_ahead: int, probability: float = 0.7, trading_periods: int = 252) -> tuple:
    """Calculate upper and lower bounds for stock price based on volatility and probability."""
    z_score = st.norm.ppf(1 - ((1 - probability) / 2))
    std_dev = z_score * stock_price * volatility * math.sqrt(days_ahead / trading_periods)
    upper_bound = round(stock_price + std_dev, 2)
    lower_bound = round(stock_price - std_dev, 2)
    return (lower_bound, upper_bound)

def get_prob(stock_price: float, strike_price: float, volatility: float, days_ahead: int, trading_periods: int = 252) -> float:
    """Calculate probability of stock price reaching strike price."""
    if any(x is None or x == 0 for x in (stock_price, strike_price, volatility, days_ahead)):
        return 0.0
    z_score = abs(stock_price - strike_price) / (stock_price * volatility * math.sqrt(days_ahead / trading_periods))
    return 2 * st.norm.cdf(z_score) - 1

def get_hist_volatility(price_df: pd.DataFrame, window: int = 30, estimator: str = 'log_returns', trading_periods: int = 252, clean: bool = True) -> pd.Series:
    """Calculate annualized historical volatility from OHLC data using specified estimator."""
    required_cols = ['close'] if estimator == 'log_returns' else ['open', 'high', 'low', 'close']
    if not all(col in price_df.columns for col in required_cols):
        raise ValueError(f"DataFrame must contain columns: {required_cols}")

    if estimator == 'log_returns':
        log_return = (price_df['close'] / price_df['close'].shift(1)).apply(np.log)
        result = log_return.rolling(window=window, center=False).std() * math.sqrt(trading_periods)

    elif estimator == 'garman_klass':
        log_hl = (price_df['high'] / price_df['low']).apply(np.log)
        log_co = (price_df['close'] / price_df['open']).apply(np.log)
        rs = 0.5 * log_hl**2 - (2 * math.log(2) - 1) * log_co**2
        result = rs.rolling(window=window, center=False).apply(lambda v: (trading_periods * v.mean())**0.5)

    elif estimator == 'hodges_tompkins':
        log_return = (price_df['close'] / price_df['close'].shift(1)).apply(np.log)
        vol = log_return.rolling(window=window, center=False).std() * math.sqrt(trading_periods)
        h = window
        n = (log_return.count() - h) + 1
        adj_factor = 1.0 / (1.0 - (h / n) + ((h**2 - 1) / (3 * n**2)))
        result = vol * adj_factor

    elif estimator == 'parkinson':
        rs = (1.0 / (4.0 * math.log(2.0))) * ((price_df['high'] / price_df['low']).apply(np.log))**2.0
        result = rs.rolling(window=window, center=False).apply(lambda v: (trading_periods * v.mean())**0.5)

    elif estimator == 'rogers_satchell':
        log_ho = (price_df['high'] / price_df['open']).apply(np.log)
        log_lo = (price_df['low'] / price_df['open']).apply(np.log)
        log_co = (price_df['close'] / price_df['open']).apply(np.log)
        rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
        result = rs.rolling(window=window, center=False).apply(lambda v: (trading_periods * v.mean())**0.5)

    elif estimator == 'yang_zhang':
        log_ho = (price_df['high'] / price_df['open']).apply(np.log)
        log_lo = (price_df['low'] / price_df['open']).apply(np.log)
        log_co = (price_df['close'] / price_df['open']).apply(np.log)
        log_oc = (price_df['open'] / price_df['close'].shift(1)).apply(np.log)
        log_oc_sq = log_oc**2
        log_cc = (price_df['close'] / price_df['close'].shift(1)).apply(np.log)
        log_cc_sq = log_cc**2
        rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
        close_vol = log_cc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
        open_vol = log_oc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
        window_rs = rs.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
        k = 0.34 / (1.34 + (window + 1) / (window - 1))
        result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(np.sqrt) * math.sqrt(trading_periods)

    else:
        raise ValueError(f"Unknown estimator: {estimator}")

    return result.dropna() if clean else result
