"""Investment Dashboard - Flask Backend"""
from flask import Flask, jsonify, request, send_from_directory
import os
import sqlite3
from db import get_db, init_db, import_from_excel_if_empty
from pricing import get_price, get_live_prices, get_fx_rate, get_timeframe_prices, get_daily_history
import pandas as pd
from datetime import datetime, timedelta

app = Flask(__name__, static_folder="static")

@app.route("/api/portfolio")
def api_portfolio():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM months ORDER BY id ASC")
    months = [dict(r) for r in c.fetchall()]
    
    c.execute("SELECT * FROM assets ORDER BY display_order ASC, id ASC")
    assets = [dict(r) for r in c.fetchall()]
    
    contributions = {a['name']: [] for a in assets}
    valuations = {a['name']: [] for a in assets} 
    price_sources = {a['name']: [] for a in assets}
    prices = {a['name']: [] for a in assets}
    prices_original = {a['name']: [] for a in assets}
    units_held = {a['name']: [] for a in assets}
    monthly_pnl = {a['name']: [] for a in assets}
    cumulative_invested = {a['name']: [] for a in assets}
    monthly_units = {a['name']: [] for a in assets}
    buy_prices = {a['name']: [] for a in assets}
    
    month_ids = [m['id'] for m in months]
    
    # PRE-FETCH FX RATES
    fx_rates = {}
    for a in assets:
        bc = a.get('buy_currency', 'EUR')
        tc = a.get('target_currency', 'EUR')
        if bc != tc and (bc, tc) not in fx_rates:
            fx_rates[(bc, tc)] = get_fx_rate(bc, tc)

    for a in assets:
        bc = a.get('buy_currency', 'EUR')
        tc = a.get('target_currency', 'EUR')
        fx_rate = fx_rates.get((bc, tc), 1.0)
        
        running_cash_target = 0.0
        prev_value_target = 0.0
        
        for mid in month_ids:
            c.execute("SELECT amount, units, buy_price FROM contributions WHERE asset_id=? AND month_id=?", (a['id'], mid))
            contrib_row = c.fetchone()
            cb_raw = contrib_row['amount'] if contrib_row else 0.0
            cu = contrib_row['units'] if contrib_row else 0.0
            cbp_raw = contrib_row['buy_price'] if contrib_row else 0.0
            
            cb_target = cb_raw * fx_rate
            
            c.execute("SELECT market_value, price, price_original, units_held, source, is_manual FROM valuations WHERE asset_id=? AND month_id=?", (a['id'], mid))
            val_row = c.fetchone()
            mv_target = val_row['market_value'] if val_row else 0.0
            
            running_cash_target += cb_target
            pnl_this_month_target = mv_target - prev_value_target - cb_target
            
            # Keep raw buy_currency amounts for editing in the frontend tables
            contributions[a['name']].append(round(cb_raw, 2))
            buy_prices[a['name']].append(round(cbp_raw, 4))
            
            # Use target_currency for everything else
            valuations[a['name']].append(round(mv_target, 2))
            prices[a['name']].append(val_row['price'] if val_row else None)
            
            po = None
            if val_row:
                po = val_row['price_original']
                if (po is None or po == 0) and val_row['price'] is not None and val_row['price'] > 0:
                    fx_rate_to_target = get_fx_rate(a.get('currency', 'EUR'), a.get('target_currency', 'EUR'))
                    po = val_row['price'] / fx_rate_to_target if fx_rate_to_target > 0 else val_row['price']
            prices_original[a['name']].append(po)
            
            units_held[a['name']].append(val_row['units_held'] if val_row else 0)
            price_sources[a['name']].append({
                "source": val_row['source'] if val_row else "manual", 
                "is_manual": val_row['is_manual'] if val_row else 1
            })
            monthly_pnl[a['name']].append(round(pnl_this_month_target, 2))
            cumulative_invested[a['name']].append(round(running_cash_target, 2))
            monthly_units[a['name']].append(round(cu, 4))
            
            prev_value_target = mv_target

    portfolio_contributions = []
    portfolio_cumulative = []
    portfolio_valuations = []
    portfolio_pnl = []
    
    for i in range(len(months)):
        tot_c = 0.0
        for a in assets:
            bc = a.get('buy_currency', 'EUR')
            tc = a.get('target_currency', 'EUR')
            fx_rate = fx_rates.get((bc, tc), 1.0)
            tot_c += contributions[a['name']][i] * fx_rate
            
        tot_cv = sum(cumulative_invested[a['name']][i] for a in assets)
        tot_v = sum(valuations[a['name']][i] for a in assets)
        tot_pnl = sum(monthly_pnl[a['name']][i] for a in assets)
        
        portfolio_contributions.append(round(tot_c, 2))
        portfolio_cumulative.append(round(tot_cv, 2))
        portfolio_valuations.append(round(tot_v, 2))
        portfolio_pnl.append(round(tot_pnl, 2))
        
    # LIVE VALUATION CALCULATION
    auto_tickers = [a['ticker'] for a in assets if a['price_source'] == 'auto' and a['ticker']]
    ticker_configs = {a['ticker']: {'currency': a.get('currency', 'EUR'), 'buy_currency': a.get('buy_currency', 'EUR'), 'target_currency': a.get('target_currency', 'EUR')} for a in assets if a['price_source'] == 'auto' and a['ticker']}
    live_prices = get_live_prices(auto_tickers, ticker_configs)
    
    live_port_value = 0.0
    asset_stats = []
    
    for a in assets:
        # Get latest units
        latest_units = units_held[a['name']][-1] if units_held[a['name']] else 0.0
        total_inv = cumulative_invested[a['name']][-1] if cumulative_invested[a['name']] else 0.0
        
        is_live_asset = False
        live_price_base = None
        live_price_target = None
        
        if a['price_source'] == 'auto' and a['ticker'] in live_prices:
            live_price_target = live_prices[a['ticker']]['target_price']
            live_price_base = live_prices[a['ticker']].get('base_price')
            current_val = latest_units * live_price_target
            is_live_asset = True
        else:
            # Fallback to last recorded month's valuation
            current_val = valuations[a['name']][-1] if valuations[a['name']] else 0.0
            live_price_target = prices[a['name']][-1] if prices[a['name']] else None
            live_price_base = prices_original[a['name']][-1] if prices_original[a['name']] else None

        if live_price_base is None and live_price_target is not None:
            # Fallback conversion from target price using fx rate
            fx_rate_to_target = get_fx_rate(a.get('currency', 'EUR'), a.get('target_currency', 'EUR'))
            live_price_base = live_price_target / fx_rate_to_target if fx_rate_to_target > 0 else live_price_target

        live_port_value += current_val
        
        pnl = current_val - total_inv
        pnl_pct = (pnl / total_inv * 100) if total_inv > 0 else 0.0
        
        total_inv_buy_curr = sum(contributions[a['name']])
        avg_buy_price_buy_curr = (total_inv_buy_curr / latest_units) if latest_units > 0 else 0.0
        avg_buy_price_target_curr = (total_inv / latest_units) if latest_units > 0 else 0.0
        
        asset_stats.append({
            "id": a['id'],
            "name": a['name'],
            "ticker": a['ticker'],
            "asset_type": a['asset_type'],
            "total_invested": round(total_inv, 2),
            "current_value": round(current_val, 2),
            "total_pnl": round(pnl, 2),
            "pnl_percent": round(pnl_pct, 2),
            "is_live": is_live_asset,
            "currency": a.get('currency', 'EUR'),
            "buy_currency": a.get('buy_currency', 'EUR'),
            "target_currency": a.get('target_currency', 'EUR'),
            "total_units": round(latest_units, 4),
            "avg_buy_price_buy_curr": round(avg_buy_price_buy_curr, 4),
            "avg_buy_price_target_curr": round(avg_buy_price_target_curr, 4),
            "current_price_base": round(live_price_base, 4) if live_price_base is not None else None,
            "current_price_target": round(live_price_target, 4) if live_price_target is not None else None
        })

    latest_port_value = portfolio_valuations[-1] if portfolio_valuations else 0.0
    latest_port_invested = portfolio_cumulative[-1] if portfolio_cumulative else 0.0
    
    # Use live value for the top-level stats
    current_value = live_port_value if live_port_value > 0 else latest_port_value
    total_pnl = current_value - latest_port_invested
    
    stats = {
        "total_invested": round(latest_port_invested, 2),
        "current_value": round(current_value, 2),
        "total_pnl": round(total_pnl, 2),
        "is_live": live_port_value > 0,
        "num_assets": len(assets),
        "num_months": len(months)
    }

    # TIMEFRAME PERFORMANCE CALCULATION (1w, 1m, YTD, 1y)
    tf_prices = get_timeframe_prices(auto_tickers, ticker_configs)
    timeframe_stats = {}
    
    for tf in ['1w', '1m', 'ytd', '1y']:
        tf_value_then = 0.0
        tf_invested_then = 0.0
        
        # Determine approximate snapshot date for this timeframe
        now = datetime.now()
        if tf == '1w': target_dt = now - timedelta(days=7)
        elif tf == '1m': target_dt = now - timedelta(days=30)
        elif tf == 'ytd': target_dt = datetime(now.year, 1, 1)
        else: target_dt = now - timedelta(days=365)
        
        # Find the month index that was active then
        # We'll use the month whose date_end is closest but <= target_dt
        snapshot_midx = -1
        for i, m in enumerate(months):
            m_dt = datetime.strptime(m['date_end'], '%Y-%m-%d')
            if m_dt <= target_dt:
                snapshot_midx = i
            else:
                break
        
        for a in assets:
            u_then = 0.0
            inv_then = 0.0
            
            if snapshot_midx >= 0:
                u_then = units_held[a['name']][snapshot_midx]
                inv_then = cumulative_invested[a['name']][snapshot_midx]
            
            p_then = 0.0
            if a['price_source'] == 'auto' and a['ticker'] in tf_prices:
                p_then = tf_prices[a['ticker']].get(tf)
            
            if not p_then or p_then == 0:
                # Fallback to DB price if auto fails or is manual
                if snapshot_midx >= 0:
                    p_then = prices[a['name']][snapshot_midx] or 0.0
                else:
                    p_then = 0.0
                    
            tf_value_then += u_then * p_then
            tf_invested_then += inv_then
            
        current_invested = stats['total_invested']
        net_contribs = current_invested - tf_invested_then
        
        tf_pnl = (stats['current_value'] - tf_value_then) - net_contribs
        # Return is calculated on the starting value + any additions during the period
        denominator = (tf_value_then + net_contribs)
        tf_pct = (tf_pnl / denominator * 100) if denominator > 0 else 0.0
        
        timeframe_stats[tf] = {
            "pnl": round(tf_pnl, 2),
            "pct": round(tf_pct, 2)
        }

    # DAILY PERFORMANCE (Last 30 days)
    daily_raw = get_daily_history(auto_tickers, days=30, ticker_configs=ticker_configs)
    
    # Generate a complete range of last 30 days to avoid gaps
    now_dt = datetime.now()
    sorted_dates = [(now_dt - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(30, -1, -1)]
    
    daily_performance = {
        "dates": sorted_dates,
        "assets": {a['name']: [] for a in assets},
        "invested": {a['name']: [] for a in assets}
    }
    
    for d_str in sorted_dates:
        for a in assets:
            # Find the most recent monthly snapshot before this date
            u_day = 0.0
            inv_day = 0.0
            m_pnl_snap = 0.0
            
            for i, m in enumerate(months):
                if m['date_end'] <= d_str:
                    u_day = units_held[a['name']][i]
                    inv_day = cumulative_invested[a['name']][i]
                    # vals[i] - cum_inv[i]
                    m_pnl_snap = valuations[a['name']][i] - cumulative_invested[a['name']][i]
                else:
                    break
            
            d_pnl = m_pnl_snap
            
            # If auto-tracked, try to get more accurate daily PnL
            if a['price_source'] == 'auto' and a['ticker'] in daily_raw:
                p_day = daily_raw[a['ticker']].get(d_str)
                if not p_day:
                    # Try finding closest prior date in daily_raw for this ticker
                    ticker_dates = sorted(daily_raw[a['ticker']].keys())
                    prior_dates = [td for td in ticker_dates if td <= d_str]
                    if prior_dates:
                        p_day = daily_raw[a['ticker']][prior_dates[-1]]
                
                if p_day and u_day > 0:
                    d_pnl = (u_day * p_day) - inv_day
            
            daily_performance["assets"][a['name']].append(round(d_pnl, 2))
            daily_performance["invested"][a['name']].append(round(inv_day, 2))

    conn.close()
    return jsonify({
        "months": months, 
        "assets": assets, 
        "contributions": contributions, 
        "cumulative_invested": cumulative_invested,
        "valuations": valuations, 
        "prices": prices,
        "prices_original": prices_original,
        "units_held": units_held,
        "monthly_pnl": monthly_pnl, 
        "price_sources": price_sources,
        "monthly_units": monthly_units,
        "buy_prices": buy_prices,
        "portfolio": {
            "contributions": portfolio_contributions,
            "cumulative": portfolio_cumulative,
            "valuations": portfolio_valuations,
            "monthly_pnl": portfolio_pnl
        },
        "stats": stats,
        "asset_stats": asset_stats,
        "timeframe_stats": timeframe_stats,
        "daily_performance": daily_performance
    })


@app.route("/api/add_month", methods=["POST"])
def api_add_month():
    body = request.get_json(force=True)
    label = body["month"].strip()
    date_end = body["date_end"].strip()

    # Validate that date_end is a real calendar date
    from datetime import datetime as _dt
    try:
        _dt.strptime(date_end, '%Y-%m-%d')
    except ValueError:
        return jsonify({"ok": False, "error": f"Invalid date: '{date_end}'. Use YYYY-MM-DD with a valid day for that month (e.g. 2026-08-31)."}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO months (label, date_end) VALUES (?, ?)", (label, date_end))
        month_id = c.lastrowid
        
        # Populate zero contribs and value=previous value for all assets
        c.execute("SELECT id FROM assets")
        assets = c.fetchall()
        for a in assets:
            c.execute("INSERT INTO contributions (asset_id, month_id, amount, units, buy_price) VALUES (?, ?, 0.0, 0.0, 0.0)", (a['id'], month_id))
            
            # Find previous month's value
            c.execute("SELECT id FROM months ORDER BY id DESC LIMIT 2")
            last_months = c.fetchall()
            prev_val = 0.0
            if len(last_months) > 1:
                prev_mid = last_months[1]['id']
                c.execute("SELECT market_value FROM valuations WHERE asset_id=? AND month_id=?", (a['id'], prev_mid))
                val_row = c.fetchone()
                if val_row:
                    prev_val = val_row['market_value']
            
            c.execute("INSERT INTO valuations (asset_id, month_id, market_value, is_manual) VALUES (?, ?, ?, 1)", (a['id'], month_id, prev_val))
            
        conn.commit()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Month already exists"}), 400
    finally:
        conn.close()

@app.route("/api/add_asset", methods=["POST"])
def api_add_asset():
    body = request.get_json(force=True)
    name = body["asset"].strip()
    asset_type = body.get("asset_type", "MANUAL")
    ticker = body.get("ticker", None)
    isin = body.get("isin", None)
    price_source = body.get("price_source", "manual")
    currency = body.get("currency", "EUR")
    buy_currency = body.get("buy_currency", "EUR")
    target_currency = body.get("target_currency", "EUR")
    
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO assets (name, asset_type, ticker, isin, price_source, currency, buy_currency, target_currency) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                  (name, asset_type, ticker, isin, price_source, currency, buy_currency, target_currency))
        asset_id = c.lastrowid
        
        c.execute("SELECT id FROM months")
        months = c.fetchall()
        for m in months:
            c.execute("INSERT INTO contributions (asset_id, month_id, amount, units, buy_price) VALUES (?, ?, 0.0, 0.0, 0.0)", (asset_id, m['id']))
            c.execute("INSERT INTO valuations (asset_id, month_id, market_value, is_manual) VALUES (?, ?, 0.0, 1)", (asset_id, m['id']))
            
        conn.commit()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "Asset already exists"}), 400
    finally:
        conn.close()

@app.route("/api/delete_asset", methods=["POST"])
def api_delete_asset():
    body = request.get_json(force=True)
    asset_id = body.get("id")
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM contributions WHERE asset_id=?", (asset_id,))
        c.execute("DELETE FROM valuations WHERE asset_id=?", (asset_id,))
        c.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/edit_asset", methods=["POST"])
def api_edit_asset():
    body = request.get_json(force=True)
    print(f"Updating asset with body: {body}")
    asset_id = body.get("id")
    if not asset_id:
        return jsonify({"ok": False, "error": "Missing asset ID"}), 400
    
    conn = get_db()
    c = conn.cursor()
    try:
        # Fetch current data to ensure NOT NULL constraints aren't violated by missing body fields
        c.execute("SELECT * FROM assets WHERE id=?", (asset_id,))
        current_asset = c.fetchone()
        if not current_asset:
            return jsonify({"ok": False, "error": "Asset not found"}), 404
            
        current = dict(current_asset)
        
        # Use provided values or keep current ones
        name = body.get("name", current["name"])
        ticker = body.get("ticker", current["ticker"])
        asset_type = body.get("asset_type", current["asset_type"])
        price_source = body.get("price_source", current["price_source"])
        currency = body.get("currency", current["currency"])
        buy_currency = body.get("buy_currency", current.get("buy_currency", "EUR"))
        target_currency = body.get("target_currency", current.get("target_currency", "EUR"))
        
        c.execute("""
            UPDATE assets 
            SET name=?, ticker=?, asset_type=?, price_source=?, currency=?, buy_currency=?, target_currency=?
            WHERE id=?
        """, (name, ticker, asset_type, price_source, currency, buy_currency, target_currency, asset_id))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error updating asset: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/reorder_asset", methods=["POST"])
def api_reorder_asset():
    body = request.get_json(force=True)
    asset_id = body.get("id")
    direction = body.get("direction") # 'up' or 'down'
    if not asset_id or direction not in ('up', 'down'):
        return jsonify({"ok": False, "error": "Invalid parameters"}), 400
        
    conn = get_db()
    c = conn.cursor()
    try:
        # Get all assets in current order
        c.execute("SELECT id, display_order FROM assets ORDER BY display_order ASC, id ASC")
        assets = [dict(r) for r in c.fetchall()]
        
        # Find current asset index
        idx = next((i for i, a in enumerate(assets) if a['id'] == asset_id), None)
        if idx is None:
            return jsonify({"ok": False, "error": "Asset not found"}), 404
            
        target_idx = idx - 1 if direction == 'up' else idx + 1
        if 0 <= target_idx < len(assets):
            # First, update all assets to have sequential display orders (0, 1, 2...)
            # to make swapping clean and resolve any default 0 display_orders
            for i, a in enumerate(assets):
                c.execute("UPDATE assets SET display_order=? WHERE id=?", (i, a['id']))
            
            # Now swap display_order of assets[idx] and assets[target_idx]
            c.execute("UPDATE assets SET display_order=? WHERE id=?", (target_idx, assets[idx]['id']))
            c.execute("UPDATE assets SET display_order=? WHERE id=?", (idx, assets[target_idx]['id']))
            
            conn.commit()
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": True, "msg": "Already at boundary"})
    except Exception as e:
        print(f"Error reordering asset: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/set_asset_order", methods=["POST"])
def api_set_asset_order():
    """Accept a full list of asset IDs in the desired display order and persist it."""
    body = request.get_json(force=True)
    ordered_ids = body.get("ids")  # list of asset IDs in desired order
    if not ordered_ids or not isinstance(ordered_ids, list):
        return jsonify({"ok": False, "error": "Expected 'ids' list"}), 400

    conn = get_db()
    c = conn.cursor()
    try:
        for idx, asset_id in enumerate(ordered_ids):
            c.execute("UPDATE assets SET display_order=? WHERE id=?", (idx, asset_id))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error setting asset order: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/delete_month", methods=["POST"])
def api_delete_month():
    body = request.get_json(force=True)
    month_id = body.get("id")
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM contributions WHERE month_id=?", (month_id,))
        c.execute("DELETE FROM valuations WHERE month_id=?", (month_id,))
        c.execute("DELETE FROM months WHERE id=?", (month_id,))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/edit_month", methods=["POST"])
def api_edit_month():
    body = request.get_json(force=True)
    month_id = body.get("id")
    new_label = body.get("label")
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("UPDATE months SET label=? WHERE id=?", (new_label, month_id))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/update_data", methods=["POST"])
def api_update_data():
    body = request.get_json(force=True)
    asset_id = body.get("asset_id")
    month_id = body.get("month_id")
    value = float(body.get("value", 0))
    update_type = body.get("type", "contribution")
    
    if not asset_id or not month_id:
        return jsonify({"ok": False, "error": "Missing asset ID or month ID"}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    try:
        c.execute("SELECT id, name, price_source, currency, buy_currency, target_currency FROM assets WHERE id=?", (asset_id,))
        asset = c.fetchone()
        c.execute("SELECT id FROM months WHERE id=?", (month_id,))
        month = c.fetchone()
        
        if not asset or not month:
            return jsonify({"ok": False, "error": "Asset or Month not found"}), 404
            
        asset = dict(asset)
            
        if update_type == 'monthly_units':
            # 1. Update units
            # 2. Get buy_price to update amount
            c.execute("SELECT buy_price FROM contributions WHERE asset_id=? AND month_id=?", (asset_id, month_id))
            row = c.fetchone()
            bp = row['buy_price'] if row and row['buy_price'] else 0.0
            
            # Fallback for bp if 0
            if bp == 0:
                c.execute("SELECT price FROM valuations WHERE asset_id=? AND month_id=?", (asset_id, month_id))
                v_row = c.fetchone()
                target_p = v_row['price'] if v_row and v_row['price'] else 0.0
                fx_rate = get_fx_rate(asset['buy_currency'], asset['target_currency'])
                bp = target_p / fx_rate if fx_rate > 0 else target_p

            amt = value * bp
            c.execute("UPDATE contributions SET units=?, amount=?, buy_price=? WHERE asset_id=? AND month_id=?", (value, amt, bp, asset_id, month_id))
            
        elif update_type == 'buy_price':
            # 1. Update buy_price
            # 2. Get units to update amount
            c.execute("SELECT units FROM contributions WHERE asset_id=? AND month_id=?", (asset_id, month_id))
            row = c.fetchone()
            u = row['units'] if row and row['units'] else 0.0
            amt = u * value
            c.execute("UPDATE contributions SET buy_price=?, amount=? WHERE asset_id=? AND month_id=?", (value, amt, asset_id, month_id))
            
        elif update_type == 'contribution':
            # Fix units based on new amount
            c.execute("SELECT buy_price FROM contributions WHERE asset_id=? AND month_id=?", (asset_id, month_id))
            row = c.fetchone()
            bp = row['buy_price'] if row and row['buy_price'] else 0.0
            
            if bp == 0:
                c.execute("SELECT price FROM valuations WHERE asset_id=? AND month_id=?", (asset_id, month_id))
                v_row = c.fetchone()
                target_p = v_row['price'] if v_row and v_row['price'] else 0.0
                fx_rate = get_fx_rate(asset['buy_currency'], asset['target_currency'])
                bp = target_p / fx_rate if fx_rate > 0 else target_p
            
            u = value / bp if bp > 0 else 0.0
            c.execute("UPDATE contributions SET amount=?, units=?, buy_price=? WHERE asset_id=? AND month_id=?", (value, u, bp, asset_id, month_id))
            
        elif update_type == 'valuation':
            c.execute("UPDATE valuations SET market_value=?, is_manual=1, source='manual' WHERE asset_id=? AND month_id=?", (value, asset_id, month_id))
            # Also update the price based on market_value / units_held
            c.execute("SELECT units_held FROM valuations WHERE asset_id=? AND month_id=?", (asset_id, month_id))
            v_row = c.fetchone()
            uh = v_row['units_held'] if v_row and v_row['units_held'] else 0.0
            if uh > 0:
                new_p = value / uh
                fx_rate_to_target = get_fx_rate(asset.get('currency', 'EUR'), asset.get('target_currency', 'EUR'))
                new_p_orig = new_p / fx_rate_to_target if fx_rate_to_target > 0 else new_p
                c.execute("UPDATE valuations SET price=?, price_original=? WHERE asset_id=? AND month_id=?", (new_p, new_p_orig, asset_id, month_id))

        # RECALCULATE ENTIRE ASSET HISTORY
        c.execute("SELECT m.id, m.label FROM months m ORDER BY m.date_end ASC")
        all_months = c.fetchall()
        u_held = 0.0
        for m in all_months:
            mid = m['id']
            c.execute("SELECT amount, units, buy_price FROM contributions WHERE asset_id=? AND month_id=?", (asset['id'], mid))
            cont = c.fetchone()
            u_held += cont['units'] if cont else 0.0
            
            c.execute("SELECT price, price_original, market_value, is_manual FROM valuations WHERE asset_id=? AND month_id=?", (asset['id'], mid))
            val = c.fetchone()
            if val:
                prc = val['price'] if val['price'] else 0.0
                prc_orig = val['price_original']
                
                # Fallback to buy price if valuation price is 0
                if prc == 0:
                    c.execute("SELECT buy_price FROM contributions WHERE asset_id=? AND month_id=?", (asset['id'], mid))
                    cont_row = c.fetchone()
                    bp = cont_row['buy_price'] if cont_row else 0.0
                    fx_rate = get_fx_rate(asset['buy_currency'], asset['target_currency'])
                    prc = bp * fx_rate
                    
                    fx_rate_orig = get_fx_rate(asset['buy_currency'], asset.get('currency', 'EUR'))
                    prc_orig = bp * fx_rate_orig
                
                if prc_orig is None or prc_orig == 0:
                    fx_rate_to_target = get_fx_rate(asset.get('currency', 'EUR'), asset.get('target_currency', 'EUR'))
                    prc_orig = prc / fx_rate_to_target if fx_rate_to_target > 0 else prc

                if update_type == 'valuation' and mid == month_id:
                    # If the user manually entered a valuation, keep that valuation but still update units_held and price_original
                    c.execute(
                        "UPDATE valuations SET units_held=?, price_original=? WHERE asset_id=? AND month_id=?",
                        (u_held, prc_orig, asset['id'], mid)
                    )
                else:
                    new_mv = u_held * prc
                    c.execute(
                        "UPDATE valuations SET units_held=?, market_value=?, price_original=? WHERE asset_id=? AND month_id=?",
                        (u_held, new_mv, prc_orig, asset['id'], mid)
                    )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error in update_data: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/update_investment_full", methods=["POST"])
def api_update_investment_full():
    body = request.get_json(force=True)
    asset_id = body.get("asset_id")
    month_id = body.get("month_id")
    amount = float(body.get("amount", 0))
    units = float(body.get("units", 0))
    buy_price = float(body.get("buy_price", 0))
    
    if not asset_id or not month_id:
        return jsonify({"ok": False, "error": "Missing asset ID or month ID"}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    try:
        c.execute("SELECT id, name, currency, buy_currency, target_currency FROM assets WHERE id=?", (asset_id,))
        asset = c.fetchone()
        if not asset:
            return jsonify({"ok": False, "error": "Asset not found"}), 404
        asset = dict(asset)
            
        # Update contributions
        c.execute("""
            UPDATE contributions 
            SET amount=?, units=?, buy_price=? 
            WHERE asset_id=? AND month_id=?
        """, (amount, units, buy_price, asset_id, month_id))
        
        # RECALCULATE ENTIRE ASSET HISTORY
        c.execute("SELECT m.id, m.label FROM months m ORDER BY m.date_end ASC")
        all_months = c.fetchall()
        u_held = 0.0
        for m in all_months:
            mid = m['id']
            # Get latest contribution data
            c.execute("SELECT units FROM contributions WHERE asset_id=? AND month_id=?", (asset_id, mid))
            cont = c.fetchone()
            u_held += cont['units'] if cont else 0.0
            
            # Update valuation
            c.execute("SELECT price, price_original FROM valuations WHERE asset_id=? AND month_id=?", (asset_id, mid))
            val = c.fetchone()
            if val:
                prc = val['price'] if val['price'] else 0.0
                prc_orig = val['price_original']
                
                # Fallback to buy price if valuation price is 0
                if prc == 0:
                    c.execute("SELECT buy_price FROM contributions WHERE asset_id=? AND month_id=?", (asset_id, mid))
                    cont_row = c.fetchone()
                    bp = cont_row['buy_price'] if cont_row else 0.0
                    fx_rate = get_fx_rate(asset['buy_currency'], asset['target_currency'])
                    prc = bp * fx_rate
                    
                    fx_rate_orig = get_fx_rate(asset['buy_currency'], asset.get('currency', 'EUR'))
                    prc_orig = bp * fx_rate_orig
                
                if prc_orig is None or prc_orig == 0:
                    fx_rate_to_target = get_fx_rate(asset.get('currency', 'EUR'), asset.get('target_currency', 'EUR'))
                    prc_orig = prc / fx_rate_to_target if fx_rate_to_target > 0 else prc

                new_mv = u_held * prc
                c.execute(
                    "UPDATE valuations SET units_held=?, market_value=?, price_original=? WHERE asset_id=? AND month_id=?",
                    (u_held, new_mv, prc_orig, asset_id, mid)
                )
        
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error in update_investment_full: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/fetch_prices", methods=["POST"])
def api_fetch_prices():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM assets WHERE price_source='auto'")
    assets = c.fetchall()

    c.execute("SELECT * FROM months ORDER BY id ASC")
    months = c.fetchall()

    query = "SELECT * FROM assets"
    df = pd.read_sql_query(query, conn)

    query = "SELECT * FROM months"
    months_df = pd.read_sql_query(query, conn)

    date_cols = months_df['label'].to_list()
    dates = pd.to_datetime(date_cols, errors='coerce').dropna()
    start_date = dates.min().strftime('%Y-%m-%d')
    end_date = (dates.max() + pd.Timedelta(days=31)).strftime('%Y-%m-%d')

    # Construct ticker configs with currency info
    auto_assets = df[df['price_source'] == 'auto']
    ticker_configs = {}
    for _, row in auto_assets.iterrows():
        if row['ticker'] and isinstance(row['ticker'], str):
            ticker_configs[row['ticker']] = {
                "currency": row.get('currency', 'EUR'),
                "buy_currency": row.get('buy_currency', 'EUR'),
                "target_currency": row.get('target_currency', 'EUR')
            }
    
    tickers = list(ticker_configs.keys())
    if not tickers:
        return jsonify({"ok": True, "fetched": 0, "msg": "No auto-tracked tickers found."})

    # Pass configs to get_price
    buy_prices_df, target_prices_df, original_prices_df = get_price(tickers, start_date, ticker_configs=ticker_configs)
    
    updates = 0
    
    for a in assets:
        units_held = 0.0
        prev_target_price = 0.0
        prev_buy_price = 0.0
        prev_original_price = 0.0
        
        for m in months:
            # Convertir la fecha del mes al formato de columna del df: "Jan 2024"
            try:
                month_col = pd.to_datetime(m["date_end"]).strftime("%b %Y")
            except Exception as date_err:
                print(f"Skipping month id={m['id']} label={m['label']}: invalid date_end='{m['date_end']}' ({date_err})")
                continue

            fetched_target_price = None
            fetched_buy_price = None
            fetched_original_price = None
            
            if a["ticker"] in target_prices_df.index and month_col in target_prices_df.columns:
                fetched_target_price = target_prices_df.loc[a["ticker"], month_col]
            if a["ticker"] in buy_prices_df.index and month_col in buy_prices_df.columns:
                fetched_buy_price = buy_prices_df.loc[a["ticker"], month_col]
            if a["ticker"] in original_prices_df.index and month_col in original_prices_df.columns:
                fetched_original_price = original_prices_df.loc[a["ticker"], month_col]
                
            # Si es NaN o None, usar el precio anterior
            if pd.notna(fetched_target_price) and fetched_target_price > 0:
                target_price = float(fetched_target_price)
                prev_target_price = target_price
            else:
                target_price = prev_target_price
                
            if pd.notna(fetched_buy_price) and fetched_buy_price > 0:
                buy_price = float(fetched_buy_price)
                prev_buy_price = buy_price
            else:
                buy_price = prev_buy_price
                
            if pd.notna(fetched_original_price) and fetched_original_price > 0:
                original_price = float(fetched_original_price)
                prev_original_price = original_price
            else:
                original_price = prev_original_price
                
            if target_price and target_price > 0 and buy_price and buy_price > 0:
                # Contribution
                c.execute(
                    "SELECT amount, units, buy_price FROM contributions WHERE asset_id=? AND month_id=?",
                    (a["id"], m["id"])
                )
                cont_row = c.fetchone()
                amount = cont_row["amount"] if cont_row else 0.0
                units_bought = cont_row["units"] if cont_row else 0.0
                
                # If units not provided, calculate them from amount and price
                if units_bought == 0 and amount > 0:
                    units_bought = amount / buy_price
                    c.execute(
                        "UPDATE contributions SET units=?, buy_price=? WHERE asset_id=? AND month_id=?",
                        (units_bought, buy_price, a["id"], m["id"])
                    )
                
                units_held += units_bought
                
                # Market value
                market_value = units_held * target_price
                
                c.execute("""
                    UPDATE valuations
                    SET price=?, price_original=?, units_held=?, market_value=?, source='auto', is_manual=0
                    WHERE asset_id=? AND month_id=?
                """, (target_price, original_price, units_held, market_value, a["id"], m["id"]))
                
                updates += 1

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "fetched": updates,
        "msg": "Prices fetched and valuations autonomously updated!"
    })

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    init_db()
    import_from_excel_if_empty()
    print("Starting Investment Dashboard on http://localhost:5050")
    app.run(debug=True, port=5050)
