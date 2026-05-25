import pandas as pd
import matplotlib.pyplot as plt
try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False
import json
import os
import numpy as np

def generate_professional_dashboard(json_path="backtesting/results.json", output_path="backtesting/pro_dashboard.png"):
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return

    with open(json_path, "r") as f:
        data = json.load(f)

    summary = data["summary"]
    equity_curve = data["equity_curve"]
    trades = pd.DataFrame(data["trades"])
    
    # Set high-end style
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(18, 12))
    gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
    fig.patch.set_facecolor('#0E1117')

    # 1. Main Equity Curve
    ax1 = fig.add_subplot(gs[0, :2])
    ax1.set_facecolor('#161B22')
    equity_series = pd.Series(equity_curve)
    ax1.plot(equity_series, color='#58A6FF', linewidth=2.5, alpha=0.9, label='Account Equity')
    
    # Drawdown Area
    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max)
    ax1.fill_between(range(len(equity_series)), equity_series, rolling_max, color='#FF7B72', alpha=0.3, label='Drawdown')
    
    ax1.set_title("Equity Curve & Drawdown Analysis", fontsize=16, fontweight='bold', color='white', pad=20)
    ax1.set_ylabel("Balance ($)", fontsize=12, color='#8B949E')
    ax1.grid(True, linestyle='--', alpha=0.1)
    ax1.legend(loc='upper left', frameon=False)

    # 2. Strategy Breakdown (Bar Chart)
    ax2 = fig.add_subplot(gs[0, 2])
    ax2.set_facecolor('#161B22')
    strat_pnl = pd.Series(data["strategy_pnl"]).sort_values()
    colors = ['#FF7B72' if x < 0 else '#3FB950' for x in strat_pnl]
    strat_pnl.plot(kind='barh', ax=ax2, color=colors)
    ax2.set_title("PnL by Strategy", fontsize=14, fontweight='bold', color='white')
    ax2.set_xlabel("Profit/Loss ($)", fontsize=10, color='#8B949E')

    # 3. Trade Distribution (Histogram)
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor('#161B22')
    if not trades.empty:
        if HAS_SEABORN:
            sns.histplot(trades['pnl'], bins=30, ax=ax3, color='#D2A8FF', kde=True, alpha=0.6)
        else:
            ax3.hist(trades['pnl'], bins=30, color='#D2A8FF', alpha=0.6)
    ax3.set_title("Trade Result Distribution", fontsize=14, fontweight='bold', color='white')
    ax3.set_xlabel("PnL ($)", fontsize=10, color='#8B949E')

    # 4. Win Rate Gauge (Pie Chart)
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor('#161B22')
    wr = summary['win_rate']
    ax4.pie([wr, 100-wr], labels=['Wins', 'Losses'], colors=['#3FB950', '#FF7B72'], 
            autopct='%1.1f%%', startangle=140, pctdistance=0.85, 
            wedgeprops={'width': 0.4, 'edgecolor': '#0E1117'})
    ax4.set_title(f"Win Rate: {wr:.1f}%", fontsize=14, fontweight='bold', color='white', y=0.45)

    # 5. Cumulative Profit Table (Metric Cards)
    ax5 = fig.add_subplot(gs[1, 2])
    ax5.axis('off')
    metrics = [
        ("Total Profit", f"${summary['total_profit']:.2f}", '#3FB950'),
        ("Total Return", f"{summary['total_profit_pct']:.2f}%", '#3FB950'),
        ("Max Drawdown", f"{summary['max_drawdown']:.2f}%", '#FF7B72'),
        ("Profit Factor", f"{summary['profit_factor']:.2f}", '#D2A8FF'),
        ("Total Trades", f"{summary['total_trades']}", '#8B949E')
    ]
    
    for i, (label, val, color) in enumerate(metrics):
        ax5.text(0.1, 0.85 - i*0.18, label, fontsize=12, color='#8B949E', fontweight='bold')
        ax5.text(0.1, 0.77 - i*0.18, val, fontsize=18, color=color, fontweight='bold')

    # 6. Monthly PnL (Heatmap Simulation)
    ax6 = fig.add_subplot(gs[2, :])
    ax6.set_facecolor('#161B22')
    if not trades.empty:
        trades['time'] = pd.to_datetime(trades['time'])
        trades['month'] = trades['time'].dt.strftime('%Y-%m')
        monthly_pnl = trades.groupby('month')['pnl'].sum()
        colors = ['#FF7B72' if x < 0 else '#3FB950' for x in monthly_pnl]
        monthly_pnl.plot(kind='bar', ax=ax6, color=colors)
        ax6.set_title("Monthly Performance Timeline", fontsize=14, fontweight='bold', color='white')
        ax6.set_ylabel("PnL ($)", fontsize=10, color='#8B949E')
        plt.xticks(rotation=45)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Professional dashboard generated at {output_path}")

if __name__ == "__main__":
    generate_professional_dashboard()
