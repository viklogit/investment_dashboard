import yfinance as yf
import pandas as pd

def get_price(tickers, start_date, ticker_configs=None):
    if not tickers:
        return pd.DataFrame(), pd.DataFrame()
    
    # Calculate required FX tickers based on configs
    fx_tickers = set()
    if ticker_configs:
        for ticker, config in ticker_configs.items():
            ticker_cur = config.get("currency", "EUR")
            buy_cur = config.get("buy_currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            if ticker_cur != buy_cur:
                fx_tickers.add(f"{ticker_cur}{buy_cur}=X")
            if ticker_cur != target_cur:
                fx_tickers.add(f"{ticker_cur}{target_cur}=X")
                
    all_tickers = tickers + list(fx_tickers)
    
    market_data = yf.download(
        all_tickers,
        start=start_date,
        interval="1mo",
        auto_adjust=False
    )

    # Normalize structure if yfinance returns a Series (single ticker)
    if 'Close' in market_data:
        close_df = market_data['Close']
        if isinstance(close_df, pd.Series):
            close_df = close_df.to_frame()
    else:
        # Fallback for unexpected data structure
        empty_df = pd.DataFrame(index=[pd.to_datetime(start_date).strftime('%b %Y')], columns=tickers).fillna(0)
        return empty_df, empty_df.copy()

    # Final prices data
    buy_df = close_df.copy()
    target_df = close_df.copy()

    # Perform conversions
    if ticker_configs:
        for ticker in tickers:
            if ticker not in close_df.columns:
                continue
                
            config = ticker_configs.get(ticker, {})
            ticker_cur = config.get("currency", "EUR")
            buy_cur = config.get("buy_currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            
            if ticker_cur != buy_cur:
                fx_ticker = f"{ticker_cur}{buy_cur}=X"
                fx_rate = close_df.get(fx_ticker)
                if fx_rate is not None:
                    buy_df[ticker] = close_df[ticker] * fx_rate
                    
            if ticker_cur != target_cur:
                fx_ticker = f"{ticker_cur}{target_cur}=X"
                fx_rate = close_df.get(fx_ticker)
                if fx_rate is not None:
                    target_df[ticker] = close_df[ticker] * fx_rate

    # Format the index
    for df in (buy_df, target_df):
        df.index = pd.to_datetime(df.index).strftime('%b %Y')
        df.columns.name = None
        df.index.name = None
    
    # Filter out FX tickers and return transposed
    available_tickers = [t for t in tickers if t in buy_df.columns]
    return buy_df[available_tickers].T, target_df[available_tickers].T

def get_live_prices(tickers, ticker_configs=None):
    """Fetch the latest available price for the given tickers and convert to target_currency and buy_currency."""
    if not tickers:
        return {}
    
    fx_tickers = set()
    if ticker_configs:
        for ticker, config in ticker_configs.items():
            ticker_cur = config.get("currency", "EUR")
            buy_cur = config.get("buy_currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            if ticker_cur != buy_cur:
                fx_tickers.add(f"{ticker_cur}{buy_cur}=X")
            if ticker_cur != target_cur:
                fx_tickers.add(f"{ticker_cur}{target_cur}=X")
                
    all_tickers = tickers + list(fx_tickers)
    
    # Download latest 1d data
    market_data = yf.download(
        all_tickers,
        period="1d",
        interval="1m",
        auto_adjust=False,
        progress=False
    )
    
    if market_data.empty:
        return {}
        
    # Get the latest 'Close' price for each ticker
    if 'Close' in market_data:
        close_df = market_data['Close']
    else:
        return {}
        
    # Handle single ticker case where yfinance might return a Series
    if isinstance(close_df, pd.Series):
        latest_prices = close_df.to_dict()
    else:
        # Get the very last non-NaN price for each column
        latest_prices = {col: close_df[col].dropna().iloc[-1] for col in close_df.columns if not close_df[col].dropna().empty}

    results = {}
    for ticker in tickers:
        base_price = latest_prices.get(ticker)
        if base_price is None:
            continue
            
        config = ticker_configs.get(ticker, {}) if ticker_configs else {}
        ticker_cur = config.get("currency", "EUR")
        buy_cur = config.get("buy_currency", "EUR")
        target_cur = config.get("target_currency", "EUR")
        
        buy_price = base_price
        target_price = base_price
        
        if ticker_cur != buy_cur:
            fx_ticker = f"{ticker_cur}{buy_cur}=X"
            fx_rate = latest_prices.get(fx_ticker)
            if fx_rate:
                buy_price = base_price * fx_rate
                
        if ticker_cur != target_cur:
            fx_ticker = f"{ticker_cur}{target_cur}=X"
            fx_rate = latest_prices.get(fx_ticker)
            if fx_rate:
                target_price = base_price * fx_rate
                
        results[ticker] = {
            'buy_price': float(buy_price),
            'target_price': float(target_price)
        }
        
    return results


def get_fx_rate(from_currency, to_currency):
    if not from_currency or not to_currency or from_currency == to_currency:
        return 1.0

    fx_ticker = f"{from_currency}{to_currency}=X"
    data = yf.download(fx_ticker, period="5d", interval="1d", auto_adjust=False, progress=False)

    if data.empty or 'Close' not in data:
        return 1.0

    close_data = data['Close']
    if hasattr(close_data, "dropna"):
        close_data = close_data.dropna()

    if len(close_data) == 0:
        return 1.0

    # single ticker case
    if hasattr(close_data, "iloc"):
        last_val = close_data.iloc[-1]
        if hasattr(last_val, "item"):
            last_val = last_val.item()
        return float(last_val)

    return 1.0