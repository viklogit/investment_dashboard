"""Investment Dashboard - Flask Backend"""
from flask import Flask, jsonify, request, send_from_directory
import os
import sqlite3
from db import get_db, init_db, import_from_excel_if_empty
from pricing import get_price, get_live_prices
import pandas as pd

app = Flask(__name__, static_folder="static")

@app.route("/api/portfolio")
def api_portfolio():
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM months ORDER BY id ASC")
    months = [dict(r) for r in c.fetchall()]
    
    c.execute("SELECT * FROM assets ORDER BY id ASC")
    assets = [dict(r) for r in c.fetchall()]
    
    contributions = {a['name']: [] for a in assets}
    valuations = {a['name']: [] for a in assets} 
    price_sources = {a['name']: [] for a in assets}
    prices = {a['name']: [] for a in assets}
    units_held = {a['name']: [] for a in assets}
    monthly_pnl = {a['name']: [] for a in assets}
    cumulative_invested = {a['name']: [] for a in assets}
    monthly_units = {a['name']: [] for a in assets}
    buy_prices = {a['name']: [] for a in assets}
    
    month_ids = [m['id'] for m in months]
    
    for a in assets:
        running_cash = 0.0
        prev_value = 0.0
        for mid in month_ids:
            c.execute("SELECT amount, units, buy_price FROM contributions WHERE asset_id=? AND month_id=?", (a['id'], mid))
            contrib_row = c.fetchone()
            cb = contrib_row['amount'] if contrib_row else 0.0
            cu = contrib_row['units'] if contrib_row else 0.0
            cbp = contrib_row['buy_price'] if contrib_row else 0.0
            
            c.execute("SELECT market_value, price, units_held, source, is_manual FROM valuations WHERE asset_id=? AND month_id=?", (a['id'], mid))
            val_row = c.fetchone()
            mv = val_row['market_value'] if val_row else 0.0
            
            running_cash += cb
            pnl_this_month = mv - prev_value - cb
            
            contributions[a['name']].append(round(cb, 2))
            valuations[a['name']].append(round(mv, 2))
            prices[a['name']].append(val_row['price'] if val_row else None)
            units_held[a['name']].append(val_row['units_held'] if val_row else 0)
            price_sources[a['name']].append({
                "source": val_row['source'] if val_row else "manual", 
                "is_manual": val_row['is_manual'] if val_row else 1
            })
            monthly_pnl[a['name']].append(round(pnl_this_month, 2))
            cumulative_invested[a['name']].append(round(running_cash, 2))
            monthly_units[a['name']].append(round(cu, 4))
            buy_prices[a['name']].append(round(cbp, 4))
            
            prev_value = mv

    portfolio_contributions = []
    portfolio_cumulative = []
    portfolio_valuations = []
    portfolio_pnl = []
    
    for i in range(len(months)):
        tot_c = sum(contributions[a['name']][i] for a in assets)
        tot_cv = sum(cumulative_invested[a['name']][i] for a in assets)
        tot_v = sum(valuations[a['name']][i] for a in assets)
        tot_pnl = sum(monthly_pnl[a['name']][i] for a in assets)
        
        portfolio_contributions.append(round(tot_c, 2))
        portfolio_cumulative.append(round(tot_cv, 2))
        portfolio_valuations.append(round(tot_v, 2))
        portfolio_pnl.append(round(tot_pnl, 2))
        
    # LIVE VALUATION CALCULATION
    auto_tickers = [a['ticker'] for a in assets if a['price_source'] == 'auto' and a['ticker']]
    ticker_configs = {a['ticker']: {'currency': a.get('currency', 'EUR')} for a in assets if a['price_source'] == 'auto' and a['ticker']}
    live_prices = get_live_prices(auto_tickers, ticker_configs)
    
    live_port_value = 0.0
    for a in assets:
        # Get latest units
        latest_units = units_held[a['name']][-1] if units_held[a['name']] else 0.0
        if a['price_source'] == 'auto' and a['ticker'] in live_prices:
            live_port_value += latest_units * live_prices[a['ticker']]
        else:
            # Fallback to last recorded month's valuation
            live_port_value += valuations[a['name']][-1] if valuations[a['name']] else 0.0

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

    
    conn.close()
    return jsonify({
        "months": months, 
        "assets": assets, 
        "contributions": contributions, 
        "cumulative_invested": cumulative_invested,
        "valuations": valuations, 
        "prices": prices,
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
        "stats": stats
    })

@app.route("/api/add_month", methods=["POST"])
def api_add_month():
    body = request.get_json(force=True)
    label = body["month"].strip()
    date_end = body["date_end"].strip()
    
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
    
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO assets (name, asset_type, ticker, isin, price_source, currency) VALUES (?, ?, ?, ?, ?, ?)", 
                  (name, asset_type, ticker, isin, price_source, currency))
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
        
        c.execute("""
            UPDATE assets 
            SET name=?, ticker=?, asset_type=?, price_source=?, currency=? 
            WHERE id=?
        """, (name, ticker, asset_type, price_source, currency, asset_id))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error updating asset: {e}")
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
        c.execute("SELECT id, name, price_source FROM assets WHERE id=?", (asset_id,))
        asset = c.fetchone()
        c.execute("SELECT id FROM months WHERE id=?", (month_id,))
        month = c.fetchone()
        
        if not asset or not month:
            return jsonify({"ok": False, "error": "Asset or Month not found"}), 404
            
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
                bp = v_row['price'] if v_row and v_row['price'] else 0.0

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
                bp = v_row['price'] if v_row and v_row['price'] else 0.0
            
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
                c.execute("UPDATE valuations SET price=? WHERE asset_id=? AND month_id=?", (new_p, asset_id, month_id))

        # RECALCULATE ENTIRE ASSET HISTORY
        c.execute("SELECT m.id, m.label FROM months m ORDER BY m.date_end ASC")
        all_months = c.fetchall()
        u_held = 0.0
        for m in all_months:
            mid = m['id']
            c.execute("SELECT amount, units, buy_price FROM contributions WHERE asset_id=? AND month_id=?", (asset['id'], mid))
            cont = c.fetchone()
            u_held += cont['units'] if cont else 0.0
            
            c.execute("SELECT price, market_value, is_manual FROM valuations WHERE asset_id=? AND month_id=?", (asset['id'], mid))
            val = c.fetchone()
            if val:
                prc = val['price'] if val['price'] else 0.0
                # If it's a manual valuation update, the price might have changed but MV is the source.
                # If it's any other update, MV should be recalculated from units_held * price.
                if update_type == 'valuation' and mid == month_id:
                    # Already updated MV and price above
                    pass
                else:
                    new_mv = u_held * prc
                    c.execute("UPDATE valuations SET units_held=?, market_value=? WHERE asset_id=? AND month_id=?", (u_held, new_mv, asset['id'], mid))
            else:
                c.execute("INSERT INTO valuations (asset_id, month_id, units_held, market_value) VALUES (?, ?, ?, 0.0)", (asset['id'], mid, u_held))

        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error in update_data: {e}")
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
                "currency": row.get('currency', 'EUR')
            }
    
    tickers = list(ticker_configs.keys())
    if not tickers:
        return jsonify({"ok": True, "fetched": 0, "msg": "No auto-tracked tickers found."})

    # Pass configs to get_price
    prices_df = get_price(tickers, start_date, ticker_configs=ticker_configs)

    updates = 0

    for a in assets:
        units_held = 0.0
        prev_price = 0.0

        for m in months:
            # Convertir la fecha del mes al formato de columna del df: "Jan 2024"
            month_col = pd.to_datetime(m["date_end"]).strftime("%b %Y")

            fetched_price = None

            if a["ticker"] in prices_df.index and month_col in prices_df.columns:
                fetched_price = prices_df.loc[a["ticker"], month_col]

            # Si es NaN o None, usar el precio anterior
            if pd.notna(fetched_price) and fetched_price > 0:
                price = float(fetched_price)
                prev_price = price
            else:
                price = prev_price

            if price and price > 0:
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
                    units_bought = amount / price
                    c.execute(
                        "UPDATE contributions SET units=?, buy_price=? WHERE asset_id=? AND month_id=?",
                        (units_bought, price, a["id"], m["id"])
                    )

                units_held += units_bought

                # Market value
                market_value = units_held * price

                c.execute("""
                    UPDATE valuations
                    SET price=?, units_held=?, market_value=?, source='auto', is_manual=0
                    WHERE asset_id=? AND month_id=?
                """, (price, units_held, market_value, a["id"], m["id"]))

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
