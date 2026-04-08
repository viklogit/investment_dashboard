# Investment Dashboard

A comprehensive, local web application designed to track, visualize, and manage your investment portfolio. Built with Flask and SQLite, it allows for granular tracking of assets (stocks, ETFs, manual entries), real-time pricing updates, and Excel synchronization.

## 🚀 Key Functionalities

1. **Real-Time Pricing & Valuation:** Auto-fetches live prices for configured tickers (Stocks/ETFs) via `yfinance`. Computes live portfolio value compared to your invested capital.
2. **Granular Asset Management:** Add, edit, or delete assets. Define tickers, ISINs, currencies (e.g., EUR, USD), and toggle between `auto` or `manual` price tracking.
3. **Tracking Units & Buy Prices:** Advanced tracking of exact units bought and their corresponding buy prices per month, ensuring precise PnL (Profit and Loss) calculations.
4. **Interactive Dashboard & Visualizations:**
   - Stacked and Line growth charts (Cumulative Invested vs. Market Value).
   - Asset Allocation Donut chart.
   - Monthly Contributions Bar chart.
   - Live Stat Cards for "Total Invested", "Current Value", and "Total P&L".
5. **Interactive Data Tables:** View and inline-edit monthly contributions, valuations, and specific asset details.
6. **Excel Synchronization:** Seed your database automatically from an Excel file, and run dedicated scripts to continuously sync units and buy prices from your spreadsheets.

---

## 🛠️ Step-by-Step Guide: How to Make it Work

### 1. Prerequisites
Ensure you have Python 3.8+ installed on your system.

### 2. Install Dependencies
Open your terminal and install the required Python libraries using the provided `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 3. Creating a New Database & Getting Started

The dashboard relies on a SQLite database (`portfolio.db`). You have two ways to start:

#### **Option A: Auto-Generate Sample Data (Easiest)**
1. Ensure no `portfolio.db` or `investments.xlsx` file exists in the directory (delete them if they do).
2. Run the application:
   ```bash
   python app.py
   ```
3. The app will automatically generate a sample `investments.xlsx` file and initialize a fresh `portfolio.db` prepopulated with dummy data.
4. Open http://localhost:5050 in your browser to explore the dashboard.

#### **Option B: Start with Your Own Excel Data**
1. Ensure no `portfolio.db` file exists in your project.
2. Create an Excel file named `investments.xlsx` in the root folder according to the [Excel Template](#-excel-file-template) below.
3. Run the application:
   ```bash
   python app.py
   ```
4. The app will parse your Excel file, create the SQLite database, and populate it with your historical months, assets, and contributions.
5. Open http://localhost:5050 in your browser.

---

## 📊 Excel File Template

If you prefer managing your numbers via Excel, ensure your `investments.xlsx` file strictly follows this structure before running the app or sync scripts.

### Sheet 1: `Monthly Investment`
*(Required for initial database seed)*
- **Row 1:** Title (ignored by parser)
- **Row 2 (Headers):** Cell A2 must be "Asset". Subsequent cells are month labels (e.g., `Jan 2024`, `Feb 2024`, `Mar 2024`...)
- **Row 3+ (Data):** Col A contains the Asset Name. Subsequent columns contain the **Monetary Contribution Amount** (cash invested) for that month.
- **Last Row:** Must start with `TOTAL PER MONTH`, `PORTFOLIO TOTAL`, or `TOTAL INVESTED` in Col A to signal the end of the table.

### Sheet 2: `Units` 
*(Required if you want to sync units via `sync_units_from_excel.py`)*
- **Row 2 (Headers):** Cell A2 must be "Asset", subsequent cells are identical month labels (e.g., `Jan 2024`).
- **Row 3+ (Data):** Col A = Asset Name. Subsequent columns = **Exact number of units** purchased that month.

### Sheet 3: `Buy Prices`
*(Required if you want to sync units via `sync_units_from_excel.py`)*
- **Row 2 (Headers):** Cell A2 must be "Asset", subsequent cells are identical month labels.
- **Row 3+ (Data):** Col A = Asset Name. Subsequent columns = **The exact price per unit** you paid that month.

---

## ⚙️ Advanced Scripts

- **Sync Units & Buy Prices:** 
  If you recorded exact units and buy prices in your Excel file (`Units` and `Buy Prices` sheets), execute this script to push that data into your database and recalculate accurate valuations:
  ```bash
  python sync_units_from_excel.py
  ```

- **Fetching Real-Time Prices:**
  While the frontend has functionality to execute this via API, you can also trigger the price fetching mechanism anytime to update the `valuations` table with the latest numbers for auto-tracked tickers.

## 📂 File Structure

```text
investment-dashboard/
│
├── app.py                      # Core Flask backend (API endpoints, calculations)
├── db.py                       # SQLite database initialization & Excel import logic
├── pricing.py                  # Live pricing integratons (yfinance & mstarpy)
├── sync_units_from_excel.py    # Script to sync 'Units' & 'Buy Prices' sheets
├── make_excel.py               # Generates the sample investments.xlsx
├── requirements.txt            # Python dependencies
│
└── static/                     # Frontend client 
    └── index.html              # Main UI (HTML, Styling, Scripts)
```
