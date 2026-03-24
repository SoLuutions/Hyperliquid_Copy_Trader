import asyncio
from typing import Callable, Optional, List, Dict
from loguru import logger
from hyperliquid.client import HyperliquidClient
from hyperliquid.websocket import HyperliquidWebSocket
from hyperliquid.models import Position, Order, UserState, WebSocketUpdate


class WalletMonitor:
    """
    Monitor a target wallet for trading activity
    """
    
    def __init__(
        self,
        target_address: str,
        api_url: str = "https://api.hyperliquid.xyz",
        ws_url: str = "wss://api.hyperliquid.xyz/ws"
    ):
        self.target_address = target_address
        self.client = HyperliquidClient(api_url)
        self.ws = HyperliquidWebSocket(ws_url)
        
        # Current state tracking
        self.current_state: Optional[UserState] = None
        self.last_positions: List[Position] = []
        self.last_orders: List[Order] = []
        self.coin_map: Dict[str, str] = {}  # Map "@107" -> "HYPE"
        
        # Callbacks
        self.on_new_position: Optional[Callable] = None
        self.on_position_update: Optional[Callable] = None
        self.on_position_close: Optional[Callable] = None
        self.on_new_order: Optional[Callable] = None
        self.on_order_fill: Optional[Callable] = None
        self.on_order_cancel: Optional[Callable] = None
        
        logger.info(f"Wallet Monitor initialized for {target_address}")
    
    async def get_current_state(self) -> Optional[UserState]:
        """Fetch current state of target wallet"""
        async with self.client:
            self.current_state = await self.client.get_user_state(self.target_address)
            
            if self.current_state:
                self.last_positions = self.current_state.positions.copy()
                self.last_orders = self.current_state.orders.copy()
            
            return self.current_state
    
    async def start_monitoring(self):
        """Start monitoring the target wallet using both WebSocket and REST polling."""
        logger.info(f"Starting monitoring for {self.target_address}")

        # Get initial state
        await self.get_current_state()

        # Load asset metadata for ID resolution
        await self._load_coin_map()

        # Connect WebSocket and subscribe
        await self.ws.connect()
        await self.ws.subscribe_user(self.target_address, self._handle_update)

        # Run WebSocket listener AND REST polling loop concurrently.
        # Polling is the safety net: it detects position changes even when
        # the target only places/cancels limit orders (no fill event fires).
        logger.info("🔄 Starting dual monitoring: WebSocket + REST polling every 10s")
        await asyncio.gather(
            self.ws.listen(),
            self._poll_loop(),
        )

    async def _poll_loop(self, interval: int = 10):
        """
        Poll the REST API every `interval` seconds and compare positions
        against the last known state. Fires the same callbacks as the
        WebSocket handler so copy trades are executed either way.
        """
        logger.info(f"📡 REST polling started (every {interval}s)")
        while True:
            await asyncio.sleep(interval)
            try:
                prev_positions = {p.symbol: p for p in (self.last_positions or [])}

                # Fetch fresh state
                await self.get_current_state()
                if not self.current_state:
                    continue

                curr_positions = {p.symbol: p for p in self.current_state.positions}

                from config.settings import settings

                for symbol, pos in curr_positions.items():
                    # Resolve symbol (in case it's an @id)
                    resolved = self._resolve_symbol(symbol)

                    # Apply asset filters
                    if settings.copy_rules.blocked_assets and resolved in settings.copy_rules.blocked_assets:
                        continue
                    if settings.copy_rules.allowed_assets and resolved not in settings.copy_rules.allowed_assets:
                        continue

                    prev = prev_positions.get(symbol)

                    # Build a minimal fill-style dict for the callback
                    size = pos.size if pos.side.value == "long" else -pos.size
                    fill_dict = {
                        "coin": resolved,
                        "side": "B" if pos.side.value == "long" else "S",
                        "sz": str(abs(pos.size)),
                        "px": str(pos.entry_price),
                        "dir": "Open Long" if pos.side.value == "long" else "Open Short",
                        "crossed": False,
                        "_source": "polling",
                    }

                    if prev is None and abs(size) > 0:
                        # Brand-new position detected by polling
                        logger.success(f"📡 POLL: NEW position detected: {resolved} {pos.side.value.upper()} {pos.size}")
                        if self.on_order_fill:
                            try:
                                if asyncio.iscoroutinefunction(self.on_order_fill):
                                    await self.on_order_fill(fill_dict)
                                else:
                                    self.on_order_fill(fill_dict)
                            except Exception as e:
                                logger.error(f"Poll callback error: {e}")

                    elif prev and abs(abs(pos.size) - abs(prev.size)) > 1e-8:
                        # Position size changed (add or partial close)
                        is_add = abs(pos.size) > abs(prev.size)
                        if is_add:
                            logger.info(f"📡 POLL: Position ADDED: {resolved} {prev.size} → {pos.size}")
                            fill_dict["dir"] = "Add Long" if pos.side.value == "long" else "Add Short"
                            if self.on_order_fill:
                                try:
                                    delta = abs(pos.size) - abs(prev.size)
                                    fill_dict["sz"] = str(delta)
                                    if asyncio.iscoroutinefunction(self.on_order_fill):
                                        await self.on_order_fill(fill_dict)
                                    else:
                                        self.on_order_fill(fill_dict)
                                except Exception as e:
                                    logger.error(f"Poll callback error: {e}")

                # Detect closed positions
                for symbol, prev in prev_positions.items():
                    if symbol not in curr_positions:
                        resolved = self._resolve_symbol(symbol)
                        logger.info(f"📡 POLL: Position CLOSED: {resolved}")
                        pos_dict = {"coin": resolved, "szi": "0"}
                        if self.on_position_close:
                            try:
                                if asyncio.iscoroutinefunction(self.on_position_close):
                                    await self.on_position_close(pos_dict)
                                else:
                                    self.on_position_close(pos_dict)
                            except Exception as e:
                                logger.error(f"Poll close callback error: {e}")

                # Update last_positions after comparison
                self.last_positions = list(self.current_state.positions)
                logger.debug(f"📡 Poll tick: {len(curr_positions)} open positions")

            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                import traceback
                logger.error(traceback.format_exc())
    
    async def stop_monitoring(self):
        """Stop monitoring"""
        logger.info("Stopping wallet monitoring")
        await self.ws.stop()
        
    async def _load_coin_map(self):
        """Fetch universe metadata to map asset IDs to symbols"""
        try:
            async with self.client:
                universe = await self.client.get_all_assets()
                for i, asset in enumerate(universe):
                    symbol = asset.get("name", "").upper()
                    if symbol:
                        self.coin_map[f"@{i}"] = symbol
                logger.info(f"✅ Loaded mapping for {len(self.coin_map)} assets")
        except Exception as e:
            logger.error(f"Failed to load coin map: {e}")

    def _resolve_symbol(self, coin: str) -> str:
        """Resolve a coin name (possibly an ID like @107) to ticker symbol"""
        if not coin:
            return ""
        
        # Check mapping
        if coin.startswith("@") and coin in self.coin_map:
            resolved = self.coin_map[coin]
            logger.debug(f"Resolved asset ID {coin} -> {resolved}")
            return resolved
            
        return coin.upper()
    
    async def _handle_update(self, update: WebSocketUpdate):
        """Handle WebSocket updates from target wallet"""
        logger.info(f"🔔 WebSocket Update Received: {update.channel}")
        
        try:
            if "data" not in update.data:
                logger.warning(f"⚠️ Update has no 'data' field: {update.data}")
                return
            
            data = update.data["data"]
            logger.info(f"📦 Update data keys: {list(data.keys())}")
            
            # Handle fills (completed trades)
            if "fills" in data:
                logger.success(f"💥 FILLS DETECTED: {len(data['fills'])} fills")
                await self._handle_fills(data["fills"])
            
            # Handle position updates
            if "positions" in data:
                logger.success(f"📊 POSITIONS UPDATE: {len(data['positions'])} positions")
                await self._handle_positions(data["positions"])
            
            # Handle order updates
            if "orders" in data:
                logger.success(f"📋 ORDERS UPDATE: {len(data['orders'])} orders")
                await self._handle_orders(data["orders"])
                
        except Exception as e:
            logger.error(f"Error handling update: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _handle_fills(self, fills: List[dict]):
        """Handle trade fills"""
        # Refresh positions before processing fills to ensure we have up-to-date state
        logger.debug("🔄 Refreshing position state before processing fills...")
        await self.get_current_state()
        
        for fill in fills:
            # Extract and resolve symbol
            raw_coin = fill.get("coin", "")
            symbol = self._resolve_symbol(raw_coin)
            
            # Check if asset is blocked or allowed
            from config.settings import settings
            if settings.copy_rules.blocked_assets and symbol in settings.copy_rules.blocked_assets:
                logger.log("TRACK", f"🚫 Target traded BLOCKED asset {symbol} (Skipping)")
                continue
                
            if settings.copy_rules.allowed_assets and symbol not in settings.copy_rules.allowed_assets:
                logger.log("TRACK", f"🐋 Target traded {symbol} (Skipped: Not in allowed list)")
                continue
            
            logger.success(f"🎯 FILL DETECTED: {fill}")
            
            if self.on_order_fill:
                try:
                    if asyncio.iscoroutinefunction(self.on_order_fill):
                        await self.on_order_fill(fill)
                    else:
                        self.on_order_fill(fill)
                except Exception as e:
                    logger.error(f"Error in fill callback: {e}")
    
    async def _handle_positions(self, positions: List[dict]):
        """Handle position updates"""
        logger.info(f"📍 Position update received: {len(positions)} positions")
        
        from config.settings import settings
        
        for pos_data in positions:
            # Parse position data
            raw_coin = pos_data.get("coin", "")
            symbol = self._resolve_symbol(raw_coin)
            size = float(pos_data.get("szi", 0))
            
            # Check if asset is blocked or allowed
            if settings.copy_rules.blocked_assets and symbol in settings.copy_rules.blocked_assets:
                logger.log("TRACK", f"🚫 Target position update: BLOCKED asset {symbol} (Skipping)")
                continue
                
            if settings.copy_rules.allowed_assets and symbol not in settings.copy_rules.allowed_assets:
                logger.log("TRACK", f"🐋 Target position update: {symbol} (Skipped: Not in allowed list)")
                continue
            
            # Check if this is a new position
            existing = next((p for p in self.last_positions if p.symbol == symbol), None)
            
            if not existing and size != 0:
                # NEW POSITION!
                logger.success(f"🆕 NEW POSITION DETECTED: {symbol}")
                
                if self.on_new_position:
                    try:
                        if asyncio.iscoroutinefunction(self.on_new_position):
                            await self.on_new_position(pos_data)
                        else:
                            self.on_new_position(pos_data)
                    except Exception as e:
                        logger.error(f"Error in new position callback: {e}")
            
            elif existing and size == 0:
                # POSITION CLOSED
                logger.info(f"❌ POSITION CLOSED: {symbol}")
                
                if self.on_position_close:
                    try:
                        if asyncio.iscoroutinefunction(self.on_position_close):
                            await self.on_position_close(pos_data)
                        else:
                            self.on_position_close(pos_data)
                    except Exception as e:
                        logger.error(f"Error in position close callback: {e}")
            
            elif existing and abs(size) != abs(existing.size):
                # POSITION SIZE CHANGED
                logger.info(f"📊 POSITION UPDATED: {symbol} ({existing.size} -> {size})")
                
                if self.on_position_update:
                    try:
                        if asyncio.iscoroutinefunction(self.on_position_update):
                            await self.on_position_update(pos_data)
                        else:
                            self.on_position_update(pos_data)
                    except Exception as e:
                        logger.error(f"Error in position update callback: {e}")
        
        # Update state
        await self.get_current_state()
    
    async def _handle_orders(self, orders: List[dict]):
        """Handle order updates"""
        logger.info(f"📝 Order update received: {len(orders)} orders")
        
        for order_data in orders:
            order_id = str(order_data.get("oid", ""))
            raw_coin = order_data.get("coin", "")
            symbol = self._resolve_symbol(raw_coin)
            
            # Check if asset is blocked or allowed
            from config.settings import settings
            if settings.copy_rules.blocked_assets and symbol in settings.copy_rules.blocked_assets:
                logger.log("TRACK", f"🚫 Target order: BLOCKED asset {symbol} (Skipping)")
                continue
                
            if settings.copy_rules.allowed_assets and symbol not in settings.copy_rules.allowed_assets:
                logger.log("TRACK", f"🐋 Target order: {symbol} (Skipped: Not in allowed list)")
                continue
            
            # Check if new order
            existing = next((o for o in self.last_orders if o.order_id == order_id), None)
            
            if not existing:
                logger.success(f"📋 NEW ORDER: {symbol} - ID: {order_id}")
                
                if self.on_new_order:
                    try:
                        if asyncio.iscoroutinefunction(self.on_new_order):
                            await self.on_new_order(order_data)
                        else:
                            self.on_new_order(order_data)
                    except Exception as e:
                        logger.error(f"Error in new order callback: {e}")
        
        # Update state
        await self.get_current_state()
