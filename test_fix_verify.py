"""
Quick verification test:
1. Imports the fixed modules (catches NameError from Bug 1 fix)
2. Checks coin_map can be built (Bug 1)
3. Checks executor signing works with a dummy action (Bug 3)
4. Connects to Hyperliquid WebSocket and listens for 15s (Bug 1 + WS)
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

async def main():
    print("=" * 60)
    print("QuantumBytes Copy Trade — Fix Verification")
    print("=" * 60)

    # --- Test 1: Import WalletMonitor without NameError ---
    print("\n[1] Importing WalletMonitor (Bug 1 fix check)...")
    try:
        from copy_engine.monitor import WalletMonitor
        print("    ✅ WalletMonitor imported successfully — no NameError")
    except NameError as e:
        print(f"    ❌ STILL BROKEN: {e}")
        return

    # --- Test 2: WalletMonitor instantiation and REST state fetch ---
    print("\n[2] Fetching target wallet state via REST API...")
    from dotenv import load_dotenv
    load_dotenv()
    target = os.getenv("TARGET_WALLET_ADDRESS", "")
    if not target:
        print("    ⚠️  No TARGET_WALLET_ADDRESS in .env — skipping REST test")
    else:
        monitor = WalletMonitor(target)
        state = await monitor.get_current_state()
        if state:
            print(f"    ✅ Got state: balance=${state.balance:.2f}, positions={len(state.positions)}")
        else:
            print("    ❌ State fetch returned None")

    # --- Test 3: Signing smoke test (Bug 3 fix check) ---
    print("\n[3] Signing smoke test (correct HL signing)...")
    try:
        from copy_engine.executor import _action_hash, _sign_l1_action
        from eth_account import Account
        dummy_action = {"type": "order", "orders": [], "grouping": "na"}
        nonce = 1234567890123
        h = _action_hash(dummy_action, None, nonce)
        print(f"    ✅ action_hash works: {h.hex()[:16]}...")

        # Full sign test (needs a real key — just test with a dummy key)
        test_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        acct = Account.from_key(test_key)
        sig = _sign_l1_action(acct, dummy_action, nonce)
        assert "r" in sig and "s" in sig and "v" in sig
        print(f"    ✅ _sign_l1_action works: v={sig['v']} r={sig['r'][:10]}...")
    except Exception as e:
        print(f"    ❌ Signing broken: {e}")
        import traceback; traceback.print_exc()

    # --- Test 4: Coin index loading (Bug 2 fix check) ---
    print("\n[4] Loading asset index map (Bug 2 fix check)...")
    try:
        from copy_engine.executor import TradeExecutor
        exec_ = TradeExecutor(
            wallet_address="0x0000000000000000000000000000000000000000",
            private_key=None,
            dry_run=True
        )
        await exec_._load_coin_index()
        btc_idx = exec_.coin_index.get("BTC")
        sol_idx = exec_.coin_index.get("SOL")
        print(f"    ✅ Loaded {len(exec_.coin_index)} assets — BTC={btc_idx}, SOL={sol_idx}")
    except Exception as e:
        print(f"    ❌ Coin index load failed: {e}")
        import traceback; traceback.print_exc()

    # --- Test 5: WebSocket connection (15 seconds) ---
    print("\n[5] WebSocket connection test (15 seconds)...")
    if not target:
        print("    ⚠️  No TARGET_WALLET_ADDRESS — skipping WS test")
    else:
        messages_received = 0
        fills_or_events = 0

        async def ws_callback(update):
            nonlocal messages_received, fills_or_events
            messages_received += 1
            ch = getattr(update, "channel", "?")
            print(f"    📨 WS message #{messages_received}: channel={ch}")
            if "fill" in str(update.data).lower() or "user" in ch.lower():
                fills_or_events += 1

        monitor2 = WalletMonitor(target)
        monitor2.on_order_fill = ws_callback

        async def listen_15s():
            await monitor2.ws.connect()
            await monitor2.ws.subscribe_user(target, monitor2._handle_update)
            try:
                await asyncio.wait_for(monitor2.ws.listen(), timeout=15)
            except asyncio.TimeoutError:
                pass

        await listen_15s()
        print(f"\n    WS messages received in 15s: {messages_received}")
        if messages_received > 0:
            print("    ✅ WebSocket is connected and receiving messages!")
        else:
            print("    ℹ️  No messages in 15s (normal if target hasn't traded — bot is still connected)")

    print("\n" + "="*60)
    print("Verification complete.")
    print("="*60)

asyncio.run(main())
