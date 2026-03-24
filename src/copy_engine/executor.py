"""Trade execution engine for Hyperliquid — correct signing and integer asset indices"""
import time
from typing import Optional, Dict, Any
from decimal import Decimal
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak
import msgpack
import aiohttp

from utils.logger import logger
from hyperliquid.models import OrderType, OrderSide


def _float_to_wire(x: float) -> str:
    """Convert float to Hyperliquid wire format string (max 8 sig figs, no trailing zeros)."""
    rounded = round(x, 8)
    if rounded == 0:
        return "0"
    s = f"{rounded:.8f}".rstrip("0").rstrip(".")
    return s


def _action_hash(action: dict, vault_address: Optional[str], nonce: int) -> bytes:
    """Msgpack-pack the action, append nonce + vaultAddress flag, keccak256-hash it."""
    data = msgpack.packb(action, use_bin_type=True)
    data += nonce.to_bytes(8, "big")
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01"
        data += bytes.fromhex(vault_address[2:] if vault_address.startswith("0x") else vault_address)
    return keccak(data)


def _sign_l1_action(account: Account, action: dict, nonce: int, vault_address: Optional[str] = None) -> dict:
    """
    Sign a Hyperliquid L1 trading action (orders, cancel, updateLeverage, etc.)
    using the official phantom-agent EIP-712 scheme.

    Flow (from hyperliquid-python-sdk/hyperliquid/utils/signing.py):
      1. msgpack-serialize action + nonce + vaultAddress flag
      2. keccak256 the result → action hash
      3. Build phantom agent: {source: "a", connectionId: <hash>}
      4. EIP-712 sign the phantom agent under the "Exchange" domain (chainId 1337)
    """
    h = _action_hash(action, vault_address, nonce)
    phantom_agent = {"source": "a", "connectionId": h}  # "a" = mainnet

    payload = {
        "domain": {
            "chainId": 1337,
            "name": "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version": "1",
        },
        "types": {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message": phantom_agent,
    }

    structured = encode_typed_data(full_message=payload)
    signed = account.sign_message(structured)

    return {
        "r": "0x" + signed.r.to_bytes(32, "big").hex(),
        "s": "0x" + signed.s.to_bytes(32, "big").hex(),
        "v": signed.v,
    }


class TradeExecutor:
    """Executes trades on Hyperliquid exchange"""

    def __init__(
        self,
        wallet_address: str,
        private_key: str,
        info_url: str = "https://api.hyperliquid.xyz/info",
        exchange_url: str = "https://api.hyperliquid.xyz/exchange",
        dry_run: bool = True
    ):
        self.wallet_address = wallet_address.lower() if wallet_address else None
        self.private_key = private_key
        self.info_url = info_url
        self.exchange_url = exchange_url
        self.dry_run = dry_run

        # coin ticker → integer asset index (populated lazily on first use)
        self.coin_index: Dict[str, int] = {}

        self.account = None
        if self.private_key and not self.dry_run:
            try:
                self.account = Account.from_key(self.private_key)
                signing_address = self.account.address
                if signing_address.lower() == self.wallet_address:
                    logger.info(f"✅ Executor initialized for wallet {self.wallet_address}")
                else:
                    logger.info(f"✅ Executor initialized — Main: {self.wallet_address} | API Key: {signing_address}")
            except Exception as e:
                logger.error(f"Failed to initialize signing account: {e}")
                raise
        elif not self.dry_run:
            raise ValueError("Cannot run in live mode without private key")
        else:
            logger.warning("⚠️ Running in DRY RUN mode - no real trades will be executed")

    async def _load_coin_index(self):
        """Fetch /info meta and build coin ticker → integer index map."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.info_url,
                    json={"type": "meta"},
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        universe = data.get("universe", [])
                        self.coin_index = {asset["name"].upper(): i for i, asset in enumerate(universe)}
                        logger.info(f"✅ Loaded {len(self.coin_index)} asset indices")
                    else:
                        logger.error(f"Failed to load asset meta: {await resp.text()}")
        except Exception as e:
            logger.error(f"Error loading coin index: {e}")

    async def _get_asset_index(self, symbol: str) -> int:
        """Return the integer asset index for a symbol, loading the map if needed."""
        if not self.coin_index:
            await self._load_coin_index()
        idx = self.coin_index.get(symbol.upper())
        if idx is None:
            logger.warning(f"⚠️ Unknown asset symbol '{symbol}', defaulting to index 0")
            return 0
        return idx

    def _build_signed_request(self, action: dict, nonce: int) -> dict:
        """Build the full signed request body for the exchange endpoint."""
        signature = _sign_l1_action(self.account, action, nonce)
        return {
            "action": action,
            "nonce": nonce,
            "signature": signature,
            "vaultAddress": None,
        }

    async def _update_leverage(self, symbol: str, leverage: int, is_cross: bool = True) -> bool:
        """Update leverage for a symbol."""
        try:
            asset_idx = await self._get_asset_index(symbol)

            action = {
                "type": "updateLeverage",
                "asset": asset_idx,   # ← must be integer index
                "isCross": is_cross,
                "leverage": int(leverage),
            }

            nonce = int(time.time() * 1000)
            request = self._build_signed_request(action, nonce)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.exchange_url,
                    json=request,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("status") == "ok":
                            logger.success(f"✅ Updated leverage for {symbol} to {leverage}x")
                            return True
                        else:
                            logger.error(f"Leverage update rejected: {result}")
                            return False
                    else:
                        logger.error(f"Failed to update leverage: {await response.text()}")
                        return False

        except Exception as e:
            logger.error(f"Error updating leverage: {e}")
            return False

    async def execute_market_order(
        self,
        symbol: str,
        side: OrderSide,
        size: Decimal,
        leverage: int = 1,
        reduce_only: bool = False
    ) -> Optional[str]:
        """Execute a market order (IOC limit at worst acceptable price)."""
        if self.dry_run:
            return await self._simulate_order(symbol, side, size, OrderType.MARKET, leverage=leverage)

        try:
            asset_idx = await self._get_asset_index(symbol)

            if leverage > 1:
                await self._update_leverage(symbol, leverage)

            is_buy = (side == OrderSide.BUY)
            # Market order = limit IOC at a very aggressive price
            # Use 0 for sells (will fill at market) and a very high price for buys — HL treats IOC at 0 as market
            action = {
                "type": "order",
                "orders": [{
                    "a": asset_idx,           # ← integer index
                    "b": is_buy,
                    "p": "0",                 # 0 = market (IOC) on Hyperliquid perps
                    "s": _float_to_wire(float(size)),
                    "r": reduce_only,
                    "t": {"limit": {"tif": "Ioc"}},
                }],
                "grouping": "na",
            }

            nonce = int(time.time() * 1000)
            request = self._build_signed_request(action, nonce)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.exchange_url,
                    json=request,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Market order response: {result}")
                        if result.get("status") == "ok":
                            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                            if statuses:
                                status = statuses[0]
                                if "filled" in status:
                                    oid = str(status["filled"].get("oid", "filled"))
                                elif "resting" in status:
                                    oid = str(status["resting"].get("oid", "resting"))
                                elif "error" in status:
                                    logger.error(f"Order error: {status['error']}")
                                    return None
                                else:
                                    oid = "executed"
                                logger.success(f"✅ Market {side.value} {symbol} size={size} leverage={leverage}x → {oid}")
                                return oid
                        logger.error(f"Order rejected: {result}")
                        return None
                    else:
                        logger.error(f"Failed to execute market order: {await response.text()}")
                        return None

        except Exception as e:
            logger.error(f"Error executing market order: {e}")
            return None

    async def execute_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        size: Decimal,
        price: Decimal,
        leverage: int = 1,
        reduce_only: bool = False,
        post_only: bool = False
    ) -> Optional[str]:
        """Execute a limit order (GTC or ALO)."""
        if self.dry_run:
            return await self._simulate_order(symbol, side, size, OrderType.LIMIT, price=price, leverage=leverage)

        try:
            asset_idx = await self._get_asset_index(symbol)

            if leverage > 1:
                await self._update_leverage(symbol, leverage)

            tif = "Alo" if post_only else "Gtc"
            action = {
                "type": "order",
                "orders": [{
                    "a": asset_idx,           # ← integer index
                    "b": (side == OrderSide.BUY),
                    "p": _float_to_wire(float(price)),
                    "s": _float_to_wire(float(size)),
                    "r": reduce_only,
                    "t": {"limit": {"tif": tif}},
                }],
                "grouping": "na",
            }

            nonce = int(time.time() * 1000)
            request = self._build_signed_request(action, nonce)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.exchange_url,
                    json=request,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Limit order response: {result}")
                        if result.get("status") == "ok":
                            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                            if statuses:
                                status = statuses[0]
                                if "resting" in status:
                                    oid = str(status["resting"].get("oid"))
                                    logger.success(f"✅ Limit {side.value} {symbol} size={size} price={price} → oid={oid}")
                                    return oid
                                elif "filled" in status:
                                    oid = str(status["filled"].get("oid", "filled"))
                                    logger.success(f"✅ Limit {side.value} {symbol} immediately filled → oid={oid}")
                                    return oid
                                elif "error" in status:
                                    logger.error(f"Order error: {status['error']}")
                                    return None
                        logger.error(f"Order rejected: {result}")
                        return None
                    else:
                        logger.error(f"Failed to place limit order: {await response.text()}")
                        return None

        except Exception as e:
            logger.error(f"Error placing limit order: {e}")
            return None

    async def close_position(
        self,
        symbol: str,
        size: Optional[Decimal] = None,
        side: Optional[OrderSide] = None
    ) -> Optional[str]:
        """Close a position using a reduce-only market order."""
        if self.dry_run:
            logger.info(f"🔵 DRY RUN: Would close position {symbol}")
            return f"dry_run_close_{symbol}_{int(time.time())}"

        # Use reduce_only market order — HL will close whatever position exists
        close_side = side if side else OrderSide.SELL
        close_size = size if size else Decimal("0.001")

        return await self.execute_market_order(
            symbol=symbol,
            side=close_side,
            size=close_size,
            reduce_only=True
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel a specific order by ID."""
        if self.dry_run:
            logger.info(f"🔵 DRY RUN: Would cancel order {order_id} for {symbol}")
            return True

        try:
            asset_idx = await self._get_asset_index(symbol)
            action = {
                "type": "cancel",
                "cancels": [{"a": asset_idx, "o": int(order_id)}],
            }

            nonce = int(time.time() * 1000)
            request = self._build_signed_request(action, nonce)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.exchange_url,
                    json=request,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("status") == "ok":
                            logger.success(f"✅ Cancelled order {order_id} for {symbol}")
                            return True
                    logger.error(f"Failed to cancel order: {await response.text()}")
                    return False

        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders (optionally filtered by symbol)."""
        if self.dry_run:
            logger.info(f"🔵 DRY RUN: Would cancel all orders{f' for {symbol}' if symbol else ''}")
            return 0

        logger.warning("cancel_all_orders requires fetching open order list — not implemented yet.")
        return 0

    async def _simulate_order(
        self,
        symbol: str,
        side: OrderSide,
        size: Decimal,
        order_type: OrderType,
        price: Optional[Decimal] = None,
        leverage: int = 1
    ) -> str:
        """Simulate an order without executing (dry run)."""
        order_id = f"sim_{symbol}_{int(time.time())}"
        if order_type == OrderType.MARKET:
            logger.info(f"🔵 DRY RUN: MARKET {side.value} {symbol} size={size} leverage={leverage}x → {order_id}")
        else:
            logger.info(f"🔵 DRY RUN: LIMIT {side.value} {symbol} size={size} price={price} leverage={leverage}x → {order_id}")
        return order_id
