from typing import Optional
from loguru import logger
from hyperliquid.models import Position, Order, UserState, PositionSide


class PositionSizer:
    """
    Calculate position sizes based on different sizing modes
    """
    
    def __init__(
        self,
        mode: str = "proportional",
        fixed_size: float = 100.0,
        portfolio_ratio: float = 0.01,
        max_position_size: float = 1000.0,
        max_total_exposure: float = 5000.0
    ):
        """
        Initialize position sizer
        
        Args:
            mode: "proportional" or "fixed"
            fixed_size: Fixed position size in USD for fixed mode
            portfolio_ratio: Ratio for proportional mode (e.g., 0.01 = 1:100)
            max_position_size: Maximum size for a single position
            max_total_exposure: Maximum total exposure across all positions
        """
        self.mode = mode
        self.fixed_size = fixed_size
        self.portfolio_ratio = portfolio_ratio
        self.max_position_size = max_position_size
        self.max_total_exposure = max_total_exposure
        
        logger.info(f"Position Sizer initialized - Mode: {mode}, Ratio: {portfolio_ratio}")
    
    def calculate_size(
        self,
        target_position: Optional[Position],
        target_wallet_balance: float,
        your_wallet_balance: float,
        your_current_exposure: float = 0,
        provided_entry_price: Optional[float] = None,
        target_size: Optional[float] = None
    ) -> Optional[float]:
        """
        Calculate size to trade
        
        Args:
            target_position: Target wallet's position object
            target_wallet_balance: Target wallet's balance
            your_wallet_balance: Your wallet's balance
            your_current_exposure: Your current total exposure
            provided_entry_price: Price to use if target_position is None
            target_size: Target size to use if target_position is None
            
        Returns:
            Position size to trade, or None if should skip
        """
        if self.mode == "proportional":
            size = self._calculate_proportional_size(
                target_position,
                target_wallet_balance,
                your_wallet_balance,
                provided_entry_price=provided_entry_price,
                target_size=target_size
            )
        else:  # fixed mode
            size = self._calculate_fixed_size(
                target_position,
                provided_entry_price=provided_entry_price
            )
        
        # Apply maximum position size limit
        if size and size > self.max_position_size:
            logger.warning(f"Position size ${size:.2f} exceeds max ${self.max_position_size:.2f}, capping")
            size = self.max_position_size
        
        # Check total exposure limit
        if size and (your_current_exposure + size) > self.max_total_exposure:
            logger.error(f"Would exceed max exposure: ${your_current_exposure + size:.2f} > ${self.max_total_exposure:.2f}")
            return None
        
        return size
    
    def _calculate_proportional_size(
        self,
        target_position: Optional[Position],
        target_wallet_balance: float,
        your_wallet_balance: float,
        provided_entry_price: Optional[float] = None,
        target_size: Optional[float] = None
    ) -> Optional[float]:
        """
        Calculate proportional size based on portfolio ratio
        """
        # Get entry price and size from position or fallbacks
        entry_price = target_position.entry_price if target_position else provided_entry_price
        size = target_position.size if target_position else target_size
        
        if entry_price is None or size is None or entry_price <= 0:
            logger.warning("Could not calculate proportional size: missing entry price or target size")
            return None
            
        # Calculate target position notional value
        target_notional = abs(size) * entry_price
        
        # Calculate the ratio between wallets
        if target_wallet_balance > 0:
            wallet_ratio = your_wallet_balance / target_wallet_balance
        else:
            wallet_ratio = self.portfolio_ratio
        
        # Calculate your position size
        your_notional = target_notional * wallet_ratio
        
        # Convert back to size (coins)
        your_size = your_notional / entry_price
        
        logger.info(
            f"Proportional sizing: Target ${target_notional:.2f} -> Your ${your_notional:.2f} "
            f"({wallet_ratio:.4f} ratio) = {your_size:.4f} coins"
        )
        
        return your_size
    
    def _calculate_fixed_size(
        self, 
        target_position: Optional[Position],
        provided_entry_price: Optional[float] = None
    ) -> Optional[float]:
        """
        Calculate fixed size regardless of target position size
        """
        entry_price = target_position.entry_price if target_position else provided_entry_price
        
        if not entry_price or entry_price <= 0:
            logger.warning("Could not calculate fixed size: missing entry price")
            return None
            
        your_size = self.fixed_size / entry_price
        
        symbol = target_position.symbol if target_position else "Unknown"
        logger.info(
            f"Fixed sizing: ${self.fixed_size:.2f} = {your_size:.4f} {symbol}"
        )
        
        return your_size

    
    def calculate_leverage(
        self,
        target_leverage: float,
        adjustment_ratio: float = 0.5,
        max_leverage: float = 10.0,
        min_leverage: float = 1.0
    ) -> float:
        """
        Calculate adjusted leverage
        
        Args:
            target_leverage: Target wallet's leverage
            adjustment_ratio: Multiply target leverage by this (e.g., 0.5 = half)
            max_leverage: Maximum allowed leverage
            min_leverage: Minimum leverage
            
        Returns:
            Adjusted leverage value
        """
        adjusted = target_leverage * adjustment_ratio
        adjusted = max(min_leverage, min(adjusted, max_leverage))
        
        logger.debug(f"Leverage adjustment: {target_leverage}x -> {adjusted}x (ratio: {adjustment_ratio})")
        
        return adjusted
    
    def should_copy_position(
        self,
        target_entry_price: float,
        current_market_price: float,
        max_entry_deviation_pct: float = 5.0
    ) -> bool:
        """
        Determine if position should be copied based on entry quality
        
        Args:
            target_entry_price: Price target entered at
            current_market_price: Current market price
            max_entry_deviation_pct: Maximum acceptable price deviation %
            
        Returns:
            True if should copy, False if price has moved too much
        """
        if target_entry_price <= 0:
            return False
        
        deviation_pct = abs(current_market_price - target_entry_price) / target_entry_price * 100
        
        if deviation_pct > max_entry_deviation_pct:
            logger.warning(
                f"Entry quality check failed: Price moved {deviation_pct:.2f}% "
                f"(max: {max_entry_deviation_pct:.2f}%)"
            )
            return False
        
        logger.info(f"Entry quality OK: {deviation_pct:.2f}% deviation")
        return True
