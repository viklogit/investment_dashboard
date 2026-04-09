import yfinance as yf
import pandas as pd

def get_price(tickers, start_date, ticker_configs=None):
    if not tickers:
        return pd.DataFrame()
    
    # Calculate required FX tickers based on configs
    fx_tickers = set()
    if ticker_configs:
        for ticker, config in ticker_configs.items():
            buy_cur = config.get("currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            if buy_cur != target_cur:
                fx_tickers.add(f"{buy_cur}{target_cur}=X")
                
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
        return pd.DataFrame(index=[pd.to_datetime(start_date).strftime('%b %Y')], columns=tickers).fillna(0)

    # Final prices data
    converted_df = close_df.copy()

    # Perform conversions
    if ticker_configs:
        for ticker in tickers:
            if ticker not in close_df.columns:
                continue
                
            config = ticker_configs.get(ticker, {})
            buy_cur = config.get("currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            
            if buy_cur != target_cur:
                fx_ticker = f"{buy_cur}{target_cur}=X"
                fx_rate = close_df.get(fx_ticker)
                
                if fx_rate is not None:
                    converted_df[ticker] = close_df[ticker] * fx_rate

    # Format the index
    converted_df.index = pd.to_datetime(converted_df.index).strftime('%b %Y')
    converted_df.columns.name = None
    converted_df.index.name = None
    
    # Filter out FX tickers and return transposed
    available_tickers = [t for t in tickers if t in converted_df.columns]
    final_data = converted_df[available_tickers].T
    return final_data

def get_live_prices(tickers, ticker_configs=None):
    """Fetch the latest available price for the given tickers and convert to target_currency."""
    if not tickers:
        return {}
    
    fx_tickers = set()
    if ticker_configs:
        for ticker, config in ticker_configs.items():
            buy_cur = config.get("currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            if buy_cur != target_cur:
                fx_tickers.add(f"{buy_cur}{target_cur}=X")
                
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
        price = latest_prices.get(ticker)
        if price is None:
            continue
            
        config = ticker_configs.get(ticker, {}) if ticker_configs else {}
        buy_cur = config.get("currency", "EUR")
        target_cur = config.get("target_currency", "EUR")
        
        if buy_cur != target_cur:
            fx_ticker = f"{buy_cur}{target_cur}=X"
            fx_rate = latest_prices.get(fx_ticker)
            if fx_rate:
                price = price * fx_rate
                
        results[ticker] = float(price)
        
    return results