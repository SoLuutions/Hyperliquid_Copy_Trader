from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os

app = FastAPI(title="Hyperliquid Copy Trader Dashboard")

# Basic routes for Health Check
@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/status")
async def get_status(request: Request):
    """Returns the live status of the bot, reading from the state injected by main.py"""
    
    # Defaults in case state is missing
    simulated_trading = getattr(request.app.state, "simulated_trading", True)
    monitor = getattr(request.app.state, "monitor", None)
    executor = getattr(request.app.state, "executor", None)
    
    data = {
        "status": getattr(request.app.state, "status", "STARTING"),
        "uptime": getattr(request.app.state, "get_uptime", lambda: 0)(),
        "target_wallet": getattr(request.app.state, "target_wallet", "Unknown"),
        "executor_wallet": getattr(request.app.state, "executor_wallet", "Unknown"),
        "trades_copied": getattr(request.app.state, "get_trades_count", lambda: 0)(),
        "mode": "SIMULATED" if simulated_trading else "LIVE"
    }
    
    if simulated_trading:
        data["balance"] = getattr(request.app.state, "get_simulated_balance", lambda: 1000)()
        data["pnl"] = getattr(request.app.state, "get_simulated_pnl", lambda: 0)()
        positions_dict = getattr(request.app.state, "get_simulated_positions", lambda: {})()
        
        # Convert simulated positions dict to a list
        pos_list = []
        for sym, p in positions_dict.items():
            pos_list.append({
                "symbol": sym,
                "size": p.get("size", 0),
                "entry_price": p.get("entry_price", 0),
                "leverage": p.get("leverage", 1),
                "side": p.get("side", ""),
                "margin": p.get("margin_used", 0)
            })
        data["positions"] = pos_list
    else:
        # LIVE Mode: Fetch the real executor wallet state directly from the HyperLiquid API
        data["balance"] = 0
        data["pnl"] = 0
        data["positions"] = []
        
        if executor and executor.wallet_address:
            try:
                state = await executor.client.get_user_state(executor.wallet_address)
                if state:
                    data["balance"] = state.balance
                    data["pnl"] = state.unrealized_pnl
                    
                    pos_list = []
                    for p in state.positions:
                        pos_list.append({
                            "symbol": p.symbol,
                            "size": p.size,
                            "entry_price": p.entry_price,
                            "current_price": p.current_price,
                            "unrealized_pnl": p.unrealized_pnl,
                            "leverage": p.leverage,
                            "side": getattr(p.side, 'value', p.side).upper() if p.side else ""
                        })
                    data["positions"] = pos_list
            except Exception as e:
                # Fallback to zero if API request fails momentarily
                pass

    return data

@app.get("/")
def serve_dashboard():
    """Serves the Vanilla HTML/CSS interface directly."""
    
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
        
    return HTMLResponse(content=html_content, status_code=200)
