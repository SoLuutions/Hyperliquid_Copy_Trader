import json
import requests
from datetime import datetime
import csv

def run_backtest():
    user_address = "0x880ac484a1743862989A441D6d867238c7AA311C"
    
    # 1. Fetch current account value of target to estimate their starting balance
    try:
        resp = requests.post("https://api.hyperliquid.xyz/info", json={
            "type": "clearinghouseState",
            "user": user_address
        })
        state = resp.json()
        current_balance = float(state.get("marginSummary", {}).get("accountValue", 0))
    except Exception as e:
        print(f"Error fetching state: {e}")
        current_balance = 10000.0  # fallback
    
    # 2. Load the fills file we saved
    try:
        with open("fills_2025.json", "r") as f:
            fills = json.load(f)
    except FileNotFoundError:
        print("Fills file not found.")
        return
        
    print(f"Loaded {len(fills)} fills.")
    
    # 3. Sort fills chronologically
    fills.sort(key=lambda x: x['time'])
    
    # Calculate target's absolute total Pnl
    target_absolute_pnl = 0.0
    for f in fills:
        pnl = float(f.get('closedPnl', 0) or 0)
        fee = float(f.get('fee', 0) or 0)
        target_absolute_pnl += (pnl - fee)
        
    estimated_starting_balance = current_balance - target_absolute_pnl
    
    # Handle massive deposit throwing off estimation
    if estimated_starting_balance <= 0 or estimated_starting_balance < current_balance * 0.05:
        print(f"Warning: Estimated starting balance ${estimated_starting_balance:,.2f} is suspicious (likely large deposits). Using dynamic ratio fallback.")
        estimated_starting_balance = current_balance * 0.5 # just a guess

    print("--- TARGET WALLET STATS ---")
    print(f"Current Eq: ${current_balance:,.2f}")
    print(f"Total PnL from Fills: ${target_absolute_pnl:,.2f}")
    print(f"Estimated Starting Eq: ${estimated_starting_balance:,.2f}")
    
    # 4. Simulate our $1000 taking proportional trades
    our_starting_balance = 1000.0
    our_balance = our_starting_balance
    
    their_virtual_balance = estimated_starting_balance
    
    history = []
    
    for f in fills:
        ts = f['time'] / 1000.0
        date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        
        pnl = float(f.get('closedPnl', 0) or 0)
        fee = float(f.get('fee', 0) or 0)
        net_trade_pnl = pnl - fee
        
        their_virtual_balance += net_trade_pnl
        
        # Calculate ratio at the time of the trade
        if their_virtual_balance <= 0:
            their_virtual_balance = 100.0 # prevent div by zero
            
        ratio = our_balance / their_virtual_balance
        
        our_trade_pnl = net_trade_pnl * ratio
        our_balance += our_trade_pnl
        
        history.append({
            "time": date,
            "target_pnl": net_trade_pnl,
            "our_pnl": our_trade_pnl,
            "our_balance": our_balance,
            "ratio": ratio,
            "coin": f.get("coin"),
            "dir": f.get("dir")
        })
        
        if our_balance < 0:
            print(f"LIQUIDATED on {date}!")
            our_balance = 0
            break

    print("\n--- $1k BACKTEST RESULTS ---")
    if not history:
        print("No trades found.")
        return
        
    print(f"Period: {history[0]['time']} to {history[-1]['time']}")
    print(f"Number of Trades: {len(history)}")
    print(f"Starting Balance: ${our_starting_balance:,.2f}")
    print(f"Ending Balance: ${our_balance:,.2f}")
    print(f"Total ROI: {((our_balance - our_starting_balance) / our_starting_balance * 100):,.2f}%")
    
    # Win rate
    wins = len([h for h in history if h['our_pnl'] > 0])
    losses = len([h for h in history if h['our_pnl'] < 0])
    winrate = wins / (wins + losses) if (wins+losses) > 0 else 0
    print(f"Win Rate (Closed Trades): {winrate*100:.1f}%")
    
    # Save a simplified CSV for the user
    with open("backtest_results.csv", "w", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=history[0].keys())
        writer.writeheader()
        writer.writerows(history)
    print("\nFull trade log saved to 'backtest_results.csv'")

if __name__ == "__main__":
    run_backtest()
