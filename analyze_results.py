import csv
from collections import defaultdict
from datetime import datetime

def analyze():
    trades = []
    with open("backtest_results.csv", "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
            
    if not trades:
        print("No trades to analyze.")
        return

    inital_balance = 1000.0
    current_balance = inital_balance
    peak_balance = inital_balance
    max_drawdown_usd = 0.0
    max_drawdown_pct = 0.0
    
    winning_trades = []
    losing_trades = []
    
    asset_pnl = defaultdict(float)
    asset_count = defaultdict(int)
    
    daily_pnl = defaultdict(float)
    
    for t in trades:
        our_pnl = float(t['our_pnl'])
        coin = t['coin']
        
        # Balance tracking
        current_balance = float(t['our_balance'])
        if current_balance > peak_balance:
            peak_balance = current_balance
            
        dd_usd = peak_balance - current_balance
        dd_pct = dd_usd / peak_balance if peak_balance > 0 else 0
        
        if dd_usd > max_drawdown_usd:
            max_drawdown_usd = dd_usd
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct
            
        # Win / Loss
        if our_pnl > 0:
            winning_trades.append(our_pnl)
        elif our_pnl < 0:
            losing_trades.append(our_pnl)
            
        # Asset stats
        asset_pnl[coin] += our_pnl
        asset_count[coin] += 1
        
        # Daily stats
        dt = datetime.strptime(t['time'], "%Y-%m-%d %H:%M:%S")
        day_str = dt.strftime("%Y-%m-%d")
        daily_pnl[day_str] += our_pnl

    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0
    
    largest_win = max(winning_trades) if winning_trades else 0
    largest_loss = min(losing_trades) if losing_trades else 0
    
    print(f"Total Trades: {len(trades)}")
    print(f"Ending Balance: ${current_balance:.2f}")
    print(f"Net Profit: ${current_balance - inital_balance:.2f}")
    print(f"Max Drawdown: {max_drawdown_pct*100:.2f}% (${max_drawdown_usd:.2f})")
    print(f"Gross Profit: ${gross_profit:.2f}")
    print(f"Gross Loss: ${gross_loss:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Average Win: ${avg_win:.2f}")
    print(f"Average Loss: ${avg_loss:.2f}")
    print(f"Largest Win: ${largest_win:.2f}")
    print(f"Largest Loss: ${largest_loss:.2f}")
    
    print("\nTop 5 Traded Assets:")
    sorted_assets_count = sorted(asset_count.items(), key=lambda x: x[1], reverse=True)[:5]
    for coin, count in sorted_assets_count:
        print(f"  {coin}: {count} trades (PnL: ${asset_pnl[coin]:.2f})")
        
    print("\nTop 5 Most Profitable Assets:")
    sorted_assets_profit = sorted(asset_pnl.items(), key=lambda x: x[1], reverse=True)[:5]
    for coin, pnl in sorted_assets_profit:
        print(f"  {coin}: ${pnl:.2f} ({asset_count[coin]} trades)")
        
    print("\nTop 5 Least Profitable Assets:")
    sorted_assets_loss = sorted(asset_pnl.items(), key=lambda x: x[1])[:5]
    for coin, pnl in sorted_assets_loss:
        print(f"  {coin}: ${pnl:.2f} ({asset_count[coin]} trades)")

if __name__ == "__main__":
    analyze()
