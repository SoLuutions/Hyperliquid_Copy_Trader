import asyncio
import json
import websockets
from typing import Optional, Callable, Dict, Any
from datetime import datetime
from loguru import logger
from .models import WebSocketUpdate

class HyperliquidWebSocket:
    """
    WebSocket client for real-time Hyperliquid data
    """
    
    def __init__(self, ws_url: str = "wss://api.hyperliquid.xyz/ws"):
        self.ws_url = ws_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_running = False
        self.reconnect_delay = 5
        self.subscriptions: Dict[str, Any] = {}
        self.callbacks: Dict[str, Callable] = {}
        
    async def connect(self):
        """Establish WebSocket connection"""
        try:
            logger.info(f"Connecting to Hyperliquid WebSocket: {self.ws_url}")
            self.ws = await websockets.connect(self.ws_url)
            self.is_running = True
            logger.info("WebSocket connected successfully")
            
            # Resubscribe to channels after reconnection
            for channel, sub_data in self.subscriptions.items():
                await self._send_subscription(sub_data)
                
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise
    
    async def disconnect(self):
        """Close WebSocket connection"""
        self.is_running = False
        if self.ws:
            await self.ws.close()
            logger.info("WebSocket disconnected")
    
    async def _send_subscription(self, data: dict):
        """Send subscription message"""
        if self.ws:
            try:
                await self.ws.send(json.dumps(data))
                logger.debug(f"Sent subscription: {data}")
            except Exception as e:
                logger.error(f"Failed to send subscription: {e}")
    
    async def subscribe_user(self, address: str, callback: Optional[Callable] = None):
        """
        Subscribe to user updates (positions, orders, fills)
        
        Args:
            address: Wallet address to monitor
            callback: Function to call when updates are received
        """
        channel = f"user:{address}"
        
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "userEvents",
                "user": address
            }
        }
        
        self.subscriptions[channel] = subscription
        if callback:
            self.callbacks[channel] = callback
        
        if self.ws:
            await self._send_subscription(subscription)
        
        logger.info(f"Subscribed to user updates for {address}")
    
    async def subscribe_trades(self, symbol: str, callback: Optional[Callable] = None):
        """
        Subscribe to trade updates for a specific symbol
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC")
            callback: Function to call when trades are received
        """
        channel = f"trades:{symbol}"
        
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "trades",
                "coin": symbol
            }
        }
        
        self.subscriptions[channel] = subscription
        if callback:
            self.callbacks[channel] = callback
        
        if self.ws:
            await self._send_subscription(subscription)
        
        logger.info(f"Subscribed to trades for {symbol}")
    
    async def subscribe_all_mids(self, callback: Optional[Callable] = None):
        """
        Subscribe to all mid prices
        
        Args:
            callback: Function to call when price updates are received
        """
        channel = "allMids"
        
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "allMids"
            }
        }
        
        self.subscriptions[channel] = subscription
        if callback:
            self.callbacks[channel] = callback
        
        if self.ws:
            await self._send_subscription(subscription)
        
        logger.info("Subscribed to all mid prices")
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            channel = data.get("channel", "unknown")

            # Suppress noisy pong/subscription confirms at INFO level
            if channel in ("pong", "subscriptionResponse"):
                logger.debug(f"WS ctrl: {channel}")
                return

            logger.debug(f"📨 WS Message: channel='{channel}' | {message[:300]}")

            update = WebSocketUpdate(
                channel=channel,
                data=data,
                timestamp=datetime.utcnow()
            )

            callback_found = False
            for callback_channel, callback in self.callbacks.items():
                should_call = False

                # 1. Exact match
                if channel == callback_channel:
                    should_call = True
                # 2. Hyperliquid sends "userEvents" for subscriptions registered as "user:0x..."
                #    So match any callback whose prefix (before ":") starts the channel string.
                elif ":" in callback_channel:
                    prefix = callback_channel.split(":")[0]  # e.g. "user"
                    if channel.startswith(prefix):           # "userEvents".startswith("user") → True
                        should_call = True
                # 3. Generic substring fallbacks
                elif callback_channel in channel:
                    should_call = True
                elif channel in callback_channel:
                    should_call = True

                if should_call:
                    callback_found = True
                    logger.info(f"✅ WS callback matched: channel='{channel}' → '{callback_channel}'")
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(update)
                        else:
                            callback(update)
                    except Exception as e:
                        logger.error(f"Error in callback for {callback_channel}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())

            if not callback_found:
                logger.warning(f"⚠️ No callback for channel: '{channel}'")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse WS message: {e} | raw={message[:200]}")
        except Exception as e:
            logger.error(f"Error handling WS message: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _ping_loop(self):
        """Send ping every 30s to keep Hyperliquid WebSocket alive.
        Without this the server closes the connection after ~60s.
        """
        while self.is_running:
            await asyncio.sleep(30)
            if self.ws and self.is_running:
                try:
                    await self.ws.send(json.dumps({"method": "ping"}))
                    logger.debug("WS ping sent")
                except Exception as e:
                    logger.warning(f"Ping failed: {e}")

    async def listen(self):
        """
        Main listening loop for WebSocket messages.
        Automatically reconnects on connection loss.
        Starts a background ping loop to keep connection alive.
        """
        # Start ping loop as a background task
        ping_task = asyncio.create_task(self._ping_loop())

        while self.is_running:
            try:
                # Handle websockets <14.0 and >=14.0 compatibility
                is_closed = True
                if self.ws:
                    if hasattr(self.ws, "closed"):
                        is_closed = self.ws.closed
                    elif hasattr(self.ws, "state"):
                        is_closed = (self.ws.state.name == "CLOSED")
                    else:
                        is_closed = False

                if is_closed:
                    await self.connect()

                async for message in self.ws:
                    await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"WebSocket connection closed, reconnecting in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)

            except Exception as e:
                logger.error(f"Error in WebSocket listener: {e}")
                await asyncio.sleep(self.reconnect_delay)

        ping_task.cancel()

    async def run(self):
        """Start the WebSocket connection and listening loop"""
        self.is_running = True
        await self.listen()

    async def stop(self):
        """Stop the WebSocket connection"""
        self.is_running = False
        await self.disconnect()
