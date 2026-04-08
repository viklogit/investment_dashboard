import yfinance as yf
import pandas as pd

def get_price(tickers, start_date, ticker_configs=None):
    if not tickers:
        return pd.DataFrame()
    
    # Always include exchange rates for conversion
    fx_tickers = ["EURUSD=X", "EURGBP=X"]
    all_tickers = tickers + fx_tickers
    
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

    # Extract FX rates
    eurusd = close_df.get("EURUSD=X")
    eurgbp = close_df.get("EURGBP=X")

    # Final prices data
    converted_df = close_df.copy()

    # Perform conversions
    if ticker_configs:
        for ticker in tickers:
            if ticker not in close_df.columns:
                continue
                
            config = ticker_configs.get(ticker, {})
            currency = config.get("currency", "EUR")
            
            if currency == "USD" and eurusd is not None:
                converted_df[ticker] = close_df[ticker] / eurusd
            elif currency == "GBP" and eurgbp is not None:
                converted_df[ticker] = close_df[ticker] / eurgbp

    # Format the index
    converted_df.index = pd.to_datetime(converted_df.index).strftime('%b %Y')
    converted_df.columns.name = None
    converted_df.index.name = None
    
    # Filter out FX tickers and return transposed
    available_tickers = [t for t in tickers if t in converted_df.columns]
    final_data = converted_df[available_tickers].T
    return final_data

def get_live_prices(tickers, ticker_configs=None):
    """Fetch the latest available price for the given tickers and convert to EUR."""
    if not tickers:
        return {}
    
    fx_tickers = ["EURUSD=X", "EURGBP=X"]
    all_tickers = tickers + fx_tickers
    
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

    eurusd = latest_prices.get("EURUSD=X")
    eurgbp = latest_prices.get("EURGBP=X")
    
    results = {}
    for ticker in tickers:
        price = latest_prices.get(ticker)
        if price is None:
            continue
            
        config = ticker_configs.get(ticker, {}) if ticker_configs else {}
        currency = config.get("currency", "EUR")
        
        # Convert to EUR
        if currency == "USD" and eurusd:
            price = price / eurusd
        elif currency == "GBP" and eurgbp:
            price = price / eurgbp
            
        results[ticker] = float(price)
        
    return results