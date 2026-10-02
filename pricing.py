import yfinance as yf
import pandas as pd

def get_price(tickers, start_date, ticker_configs=None):
    if not tickers:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
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
        return empty_df, empty_df.copy(), empty_df.copy()

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
    for df in (buy_df, target_df, close_df):
        df.index = pd.to_datetime(df.index).strftime('%b %Y')
        df.columns.name = None
        df.index.name = None
    
    # Filter out FX tickers and return transposed
    available_tickers = [t for t in tickers if t in buy_df.columns]
    return buy_df[available_tickers].T, target_df[available_tickers].T, close_df[available_tickers].T

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
            if fx_rate is None or (hasattr(fx_rate, "isna") and fx_rate.isna()) or (isinstance(fx_rate, float) and pd.isna(fx_rate)):
                fx_rate = get_fx_rate(ticker_cur, buy_cur)
            if fx_rate:
                buy_price = base_price * fx_rate
                
        if ticker_cur != target_cur:
            fx_ticker = f"{ticker_cur}{target_cur}=X"
            fx_rate = latest_prices.get(fx_ticker)
            if fx_rate is None or (hasattr(fx_rate, "isna") and fx_rate.isna()) or (isinstance(fx_rate, float) and pd.isna(fx_rate)):
                fx_rate = get_fx_rate(ticker_cur, target_cur)
            if fx_rate:
                target_price = base_price * fx_rate
                
        results[ticker] = {
            'buy_price': float(buy_price),
            'target_price': float(target_price),
            'base_price': float(base_price)
        }
        
    return results


def get_daily_history(tickers, days=30, ticker_configs=None):
    """
    Fetch daily historical prices for the last N days.
    Returns a dict: { ticker: { date_iso_string: price } }
    """
    if not tickers:
        return {}

    from datetime import datetime, timedelta
    now = datetime.now()
    start_date = (now - timedelta(days=days + 5)).strftime('%Y-%m-%d')
    
    fx_tickers = set()
    if ticker_configs:
        for ticker, config in ticker_configs.items():
            ticker_cur = config.get("currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            if ticker_cur != target_cur:
                fx_tickers.add(f"{ticker_cur}{target_cur}=X")
                
    all_tickers = tickers + list(fx_tickers)
    data = yf.download(all_tickers, start=start_date, interval="1d", auto_adjust=False, progress=False)
    
    if data.empty or 'Close' not in data:
        return {}
    
    close_df = data['Close']
    if isinstance(close_df, pd.Series):
        close_df = close_df.to_frame()
        
    results = {t: {} for t in tickers}
    for ticker in tickers:
        if ticker not in close_df.columns:
            continue
            
        config = ticker_configs.get(ticker, {}) if ticker_configs else {}
        ticker_cur = config.get("currency", "EUR")
        target_cur = config.get("target_currency", "EUR")
        fx_ticker = f"{ticker_cur}{target_cur}=X" if ticker_cur != target_cur else None
        
        valid_prices = close_df[ticker].dropna()
        for date, price in valid_prices.items():
            date_str = date.strftime('%Y-%m-%d')
            
            target_price = price
            if fx_ticker:
                fx_rate = None
                if fx_ticker in close_df.columns:
                    fx_rate = close_df.loc[date, fx_ticker]
                    if pd.isna(fx_rate):
                        # Find nearest FX rate
                        v_fx = close_df[fx_ticker].dropna()
                        if not v_fx.empty:
                            idx = v_fx.index.get_indexer([date], method='nearest')[0]
                            fx_rate = v_fx.iloc[idx]
                if fx_rate is None or pd.isna(fx_rate):
                    fx_rate = get_fx_rate(ticker_cur, target_cur)
                if fx_rate:
                    target_price = price * fx_rate
                
            results[ticker][date_str] = float(target_price)
            
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


def get_timeframe_prices(tickers, ticker_configs=None):
    """
    Fetch historical prices for 1w, 1m, YTD, and 1y ago.
    Returns a dict: { ticker: { '1w': price, '1m': price, 'ytd': price, '1y': price } }
    """
    if not tickers:
        return {}

    from datetime import datetime, timedelta
    now = datetime.now()
    
    # Calculate intervals
    intervals = {
        '1w': now - timedelta(days=7),
        '1m': now - timedelta(days=30),
        'ytd': datetime(now.year, 1, 1),
        '1y': now - timedelta(days=365)
    }
    
    # We need to fetch enough data to cover all intervals
    start_date = (now - timedelta(days=375)).strftime('%Y-%m-%d')
    
    # Collect all needed FX tickers
    fx_tickers = set()
    if ticker_configs:
        for _, config in ticker_configs.items():
            ticker_cur = config.get("currency", "EUR")
            target_cur = config.get("target_currency", "EUR")
            if ticker_cur != target_cur:
                fx_tickers.add(f"{ticker_cur}{target_cur}=X")
                
    all_tickers = tickers + list(fx_tickers)
    
    # Download daily data for the last year+
    data = yf.download(all_tickers, start=start_date, interval="1d", auto_adjust=False, progress=False)
    
    if data.empty or 'Close' not in data:
        return {}
    
    close_df = data['Close']
    
    # Handle single ticker case
    if isinstance(close_df, pd.Series):
        close_df = close_df.to_frame()

    results = {t: {} for t in tickers}
    for ticker in tickers:
        if ticker not in close_df.columns:
            continue
            
        config = ticker_configs.get(ticker, {}) if ticker_configs else {}
        ticker_cur = config.get("currency", "EUR")
        target_cur = config.get("target_currency", "EUR")
        fx_ticker = f"{ticker_cur}{target_cur}=X" if ticker_cur != target_cur else None

        for label, target_date in intervals.items():
            try:
                # Find the closest available date in the index
                target_dt = pd.to_datetime(target_date).normalize()
                idx = close_df.index.get_indexer([target_dt], method='nearest')[0]
                if idx == -1:
                    results[ticker][label] = None
                    continue
                    
                base_price = close_df.iloc[idx][ticker]
                
                if pd.isna(base_price):
                    # Search backwards for a non-NaN value if needed
                    valid_prices = close_df[ticker].dropna()
                    if not valid_prices.empty:
                        v_idx = valid_prices.index.get_indexer([target_dt], method='nearest')[0]
                        base_price = valid_prices.iloc[v_idx]
                    else:
                        results[ticker][label] = None
                        continue

                # Convert to target currency
                target_price = base_price
                if fx_ticker:
                    fx_rate = None
                    if fx_ticker in close_df.columns:
                        fx_rate = close_df.iloc[idx][fx_ticker]
                        if pd.isna(fx_rate):
                            v_fx = close_df[fx_ticker].dropna()
                            if not v_fx.empty:
                                fv_idx = v_fx.index.get_indexer([target_dt], method='nearest')[0]
                                fx_rate = v_fx.iloc[fv_idx]
                    if fx_rate is None or pd.isna(fx_rate):
                        fx_rate = get_fx_rate(ticker_cur, target_cur)
                    if fx_rate:
                        target_price = base_price * fx_rate
                    
                results[ticker][label] = float(target_price)
            except Exception:
                results[ticker][label] = None
        
    return results


def get_benchmark_data(months, portfolio_contributions, portfolio_valuations, start_month_idx=0):
    """
    Computes monthly comparison between Portfolio and S&P500, MSCI World, Nasdaq 100.
    1. Isolated Monthly Growth % (TWR per month)
    2. Simulated Cumulative Value (€) if total monthly contributions had been invested 100% in each index starting from start_month_idx.
    """
    if not months:
        return {}

    benchmarks_config = {
        'sp500': {'ticker': '0P00000G12.F', 'name': 'S&P 500'},
        'msci': {'ticker': '0P0001CLDK.F', 'name': 'MSCI World'},
        'nasdaq': {'ticker': 'XNAS.DE', 'name': 'Nasdaq 100'}
    }

    tickers = [b['ticker'] for b in benchmarks_config.values()]

    # Fetch daily close data starting prior to the first month
    first_date = months[0]['date_end']
    from datetime import datetime, timedelta
    start_dt = (datetime.strptime(first_date, '%Y-%m-%d') - timedelta(days=65)).strftime('%Y-%m-%d')

    try:
        data = yf.download(tickers, start=start_dt, interval="1d", auto_adjust=False, progress=False)
        if data.empty or 'Close' not in data:
            return {}
        close_df = data['Close']
        if isinstance(close_df, pd.Series):
            close_df = close_df.to_frame()
    except Exception:
        return {}

    # Helper to get price on or before date
    def get_price_at(ticker, date_str):
        if ticker not in close_df.columns:
            return None
        s = close_df[ticker].dropna()
        dt = pd.to_datetime(date_str)
        valid = s[s.index <= dt]
        if not valid.empty:
            return float(valid.iloc[-1])
        return None

    # Calculate portfolio monthly isolated % return
    # PnL_m = V_m - V_{m-1} - C_m
    # Ret_m = PnL_m / (V_{m-1} + C_m) if (V_{m-1} + C_m) > 0 else 0
    portfolio_monthly_pct = []
    for i in range(len(months)):
        v_curr = portfolio_valuations[i] if i < len(portfolio_valuations) else 0.0
        v_prev = portfolio_valuations[i-1] if i > 0 and (i-1) < len(portfolio_valuations) else 0.0
        c_curr = portfolio_contributions[i] if i < len(portfolio_contributions) else 0.0

        pnl = v_curr - v_prev - c_curr
        denom = v_prev + c_curr
        pct = (pnl / denom * 100.0) if denom > 0 else 0.0
        portfolio_monthly_pct.append(round(pct, 2))

    # Compute benchmarks performance
    benchmark_monthly_pct = {k: [] for k in benchmarks_config.keys()}
    benchmark_cumulative_sim = {k: [] for k in benchmarks_config.keys()}

    # Initialize simulated units held for each benchmark
    benchmark_units = {k: 0.0 for k in benchmarks_config.keys()}

    # We also compute simulated portfolio value for My Portfolio from start_month_idx if user filters
    # If start_month_idx > 0, portfolio_cumulative_sim starts from initial valuation at start_month_idx or 0
    start_val = portfolio_valuations[start_month_idx-1] if start_month_idx > 0 and (start_month_idx-1) < len(portfolio_valuations) else 0.0

    for i, m in enumerate(months):
        date_curr = m['date_end']
        contrib = portfolio_contributions[i] if i < len(portfolio_contributions) else 0.0

        # Prior month date (or ~30 days prior for first month baseline)
        if i == 0:
            date_prev = (datetime.strptime(date_curr, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
        else:
            date_prev = months[i-1]['date_end']

        for key, info in benchmarks_config.items():
            t = info['ticker']
            p_curr = get_price_at(t, date_curr)
            p_prev = get_price_at(t, date_prev)

            # Monthly % return
            if p_curr and p_prev and p_prev > 0:
                m_pct = ((p_curr - p_prev) / p_prev) * 100.0
            else:
                m_pct = 0.0
            benchmark_monthly_pct[key].append(round(m_pct, 2))

            # Cumulative simulated portfolio calculation starting from start_month_idx
            p_buy = p_curr or p_prev
            if i >= start_month_idx:
                # If first month of filter and we want to include initial starting valuation:
                if i == start_month_idx and start_val > 0 and p_buy and p_buy > 0:
                    benchmark_units[key] += (start_val / p_buy)
                
                if p_buy and p_buy > 0 and contrib > 0:
                    benchmark_units[key] += (contrib / p_buy)

                sim_val = benchmark_units[key] * (p_curr or 0.0)
            else:
                sim_val = 0.0

            benchmark_cumulative_sim[key].append(round(sim_val, 2))

    return {
        "portfolio_monthly_pct": portfolio_monthly_pct,
        "benchmarks": {
            "sp500": {
                "name": benchmarks_config['sp500']['name'],
                "monthly_pct": benchmark_monthly_pct['sp500'],
                "cumulative_sim": benchmark_cumulative_sim['sp500']
            },
            "msci": {
                "name": benchmarks_config['msci']['name'],
                "monthly_pct": benchmark_monthly_pct['msci'],
                "cumulative_sim": benchmark_cumulative_sim['msci']
            },
            "nasdaq": {
                "name": benchmarks_config['nasdaq']['name'],
                "monthly_pct": benchmark_monthly_pct['nasdaq'],
                "cumulative_sim": benchmark_cumulative_sim['nasdaq']
            }
        }
    }