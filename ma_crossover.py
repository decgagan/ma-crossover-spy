"""
Moving-average crossover (momentum) backtest on SPY.

Flow: download -> DataFrame -> squeeze -> rolling means -> signal -> SHIFT
      -> returns -> costs -> cumprod -> metrics/plots

Educational project only. Not financial advice.
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

START = "2005-01-01"
TRADING_DAYS = 252
CHARTS = "charts"


# ---------- FIXED PLUMBING (same in almost any backtest) ----------

def download_close(ticker, start=START):
    """Daily closes, adjusted for splits and dividends (auto_adjust=True)."""
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    return df["Close"].squeeze().dropna()   # squeeze: 1-column table -> Series


def backtest(close, fast=50, slow=200, cost=0.001, shift=True):
    """Return daily strategy returns and the position used each day.

    shift=True means today's position uses yesterday's signal (no lookahead).
    shift=False is deliberately WRONG and only used for the sanity check.
    """
    fast_ma = close.rolling(fast).mean()               # TUNABLE: window lengths
    slow_ma = close.rolling(slow).mean()
    signal = (fast_ma > slow_ma).astype(int)           # TUNABLE: signal rule
    signal[slow_ma.isna()] = 0                         # no signal before MAs exist
    position = signal.shift(1).fillna(0) if shift else signal
    daily_ret = close.pct_change().fillna(0)
    strat = position * daily_ret
    trades = position.diff().abs().fillna(0)           # 1 on every buy or sell day
    strat = strat - trades * cost                      # TUNABLE: cost assumption
    return strat, position, trades


def metrics(returns, position=None, trades=None):
    """Headline statistics for a series of daily returns."""
    equity = (1 + returns).cumprod()
    years = len(returns) / TRADING_DAYS
    cagr = equity.iloc[-1] ** (1 / years) - 1
    vol = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = returns.mean() / returns.std() * np.sqrt(TRADING_DAYS)  # rf = 0
    max_dd = (equity / equity.cummax() - 1).min()
    out = {"Final £1": equity.iloc[-1], "CAGR": cagr, "Ann. vol": vol,
           "Sharpe": sharpe, "Max DD": max_dd}
    out["Time in mkt"] = position.mean() if position is not None else 1.0
    out["Trades"] = int(trades.sum()) if trades is not None else 1
    return out


def evaluate(close, start=None, end=None, **kw):
    """Run the strategy on full history (so MAs warm up), score only start..end."""
    strat, pos, tr = backtest(close, **kw)
    sl = slice(start, end)
    return metrics(strat[sl], pos[sl], tr[sl]), strat[sl]


def buy_hold(close, start=None, end=None):
    r = close.pct_change().fillna(0)[start:end]
    return metrics(r), r


def fmt(rows):
    df = pd.DataFrame(rows).T
    for c in ["CAGR", "Ann. vol", "Max DD", "Time in mkt"]:
        df[c] = (df[c] * 100).map("{:.1f}%".format)
    df["Final £1"] = df["Final £1"].map("£{:.2f}".format)
    df["Sharpe"] = df["Sharpe"].map("{:.2f}".format)
    return df.to_markdown()


def main():
    import os
    os.makedirs(CHARTS, exist_ok=True)
    spy = download_close("SPY")
    # Score everything from the day the longest window (250) is available,
    # so every comparison covers exactly the same period.
    eval_start = spy.index[250]
    report = [f"Data: SPY {spy.index[0].date()} to {spy.index[-1].date()}; "
              f"scored from {eval_start.date()}\n"]

    # (1) Baseline vs buy & hold
    m_s, r_s = evaluate(spy, eval_start)
    m_b, r_b = buy_hold(spy, eval_start)
    report += ["## 1. Baseline 50/200, 0.1% cost", fmt({"Buy & hold": m_b, "MA 50/200": m_s})]
    eq = pd.DataFrame({"Buy & hold": (1 + r_b).cumprod(), "MA 50/200": (1 + r_s).cumprod()})
    eq.plot(logy=True, title="SPY: 50/200 MA crossover vs buy & hold (growth of £1, log)")
    plt.tight_layout(); plt.savefig(f"{CHARTS}/equity_curve.png", dpi=120); plt.close()
    (eq / eq.cummax() - 1).plot(title="Drawdowns from previous peak")
    plt.tight_layout(); plt.savefig(f"{CHARTS}/drawdowns.png", dpi=120); plt.close()

    # (2) Cost sensitivity
    rows = {f"cost {c*100:.2f}%": evaluate(spy, eval_start, cost=c)[0]
            for c in [0, 0.001, 0.0025, 0.005]}
    rows["Buy & hold"] = m_b
    report += ["## 2. Cost sensitivity (50/200)", fmt(rows)]

    # (3) Parameter grid, full period
    fasts, slows = [20, 50, 100], [100, 150, 200, 250]
    grid = pd.DataFrame(index=fasts, columns=slows, dtype=float)
    for f in fasts:
        for s in slows:
            if f < s:
                grid.loc[f, s] = evaluate(spy, eval_start, fast=f, slow=s)[0]["Sharpe"]
    report += ["## 3. Sharpe grid, full period (rows fast, cols slow); buy & hold "
               f"Sharpe {m_b['Sharpe']:.2f}", grid.round(2).to_markdown()]
    heat(grid, "Sharpe by window (full period, 0.1% cost)", f"{CHARTS}/heatmap_sharpe.png")

    # (4) In-sample pick, out-of-sample test
    is_grid = pd.DataFrame(index=fasts, columns=slows, dtype=float)
    for f in fasts:
        for s in slows:
            if f < s:
                is_grid.loc[f, s] = evaluate(spy, eval_start, "2015-12-31", fast=f, slow=s)[0]["Sharpe"]
    bf, bs = is_grid.stack().idxmax()
    report += [f"## 4. In-sample 2005-2015 Sharpe grid (best: {bf}/{bs})",
               is_grid.round(2).to_markdown()]
    oos = "2016-01-01"
    m_c, r_c = evaluate(spy, oos, fast=bf, slow=bs)
    m_d, r_d = evaluate(spy, oos)
    m_bo, r_bo = buy_hold(spy, oos)
    report += ["### Out-of-sample 2016 to present",
               fmt({f"Chosen {bf}/{bs}": m_c, "Default 50/200": m_d, "Buy & hold": m_bo})]
    pd.DataFrame({f"Chosen {bf}/{bs}": (1 + r_c).cumprod(), "Default 50/200": (1 + r_d).cumprod(),
                  "Buy & hold": (1 + r_bo).cumprod()}).plot(
        logy=True, title="Out-of-sample 2016 to present (growth of £1, log)")
    plt.tight_layout(); plt.savefig(f"{CHARTS}/out_of_sample.png", dpi=120); plt.close()

    # (5) Other tickers, default params
    rows = {}
    for t in ["QQQ", "EFA"]:
        c = download_close(t)
        st = c.index[250]
        rows[f"{t} buy & hold"] = buy_hold(c, st)[0]
        rows[f"{t} MA 50/200"] = evaluate(c, st)[0]
    report += ["## 5. Other tickers (50/200, 0.1% cost)", fmt(rows)]

    # (6) Lookahead sanity check
    report += ["## 6. Lookahead bias check (50/200)", fmt({
        "With shift(1) (correct)": m_s,
        "Without shift (WRONG)": evaluate(spy, eval_start, shift=False)[0],
        "Buy & hold": m_b})]

    text = "\n\n".join(report)
    open("results.md", "w").write(text)
    print(text)


def heat(grid, title, path):
    fig, ax = plt.subplots()
    im = ax.imshow(grid.values.astype(float), cmap="viridis")
    ax.set_xticks(range(len(grid.columns)), grid.columns)
    ax.set_yticks(range(len(grid.index)), grid.index)
    ax.set_xlabel("Slow window (days)"); ax.set_ylabel("Fast window (days)")
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid.iloc[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", color="w")
    fig.colorbar(im, label="Sharpe"); ax.set_title(title)
    plt.tight_layout(); plt.savefig(path, dpi=120); plt.close()


if __name__ == "__main__":
    main()
