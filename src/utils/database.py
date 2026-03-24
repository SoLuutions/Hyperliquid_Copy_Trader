import os
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from loguru import logger

Base = declarative_base()

class TradeRecord(Base):
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String, index=True)
    side = Column(String)  # "LONG", "SHORT"
    size = Column(Float)
    price = Column(Float)
    leverage = Column(Integer)
    notional_value = Column(Float)
    order_id = Column(String, nullable=True) # If available from HL (usually isn't for market)
    status = Column(String, default="FILLED") # FILLED, FAILED
    source = Column(String) # "websocket", "polling"
    
    def __repr__(self):
        return f"<TradeRecord(symbol={self.symbol}, side={self.side}, size={self.size}, px={self.price})>"

class DatabaseManager:
    """Handles SQLite database interactions using SQLAlchemy"""
    
    def __init__(self, db_url: str = "sqlite:///./data/trading.db"):
        self.db_url = db_url
        
        # Ensure data directory exists
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create tables
        Base.metadata.create_all(bind=self.engine)
        logger.info(f"💾 Database initialized: {db_url}")

    def get_session(self) -> Session:
        return self.SessionLocal()

    def add_trade(self, symbol: str, side: str, size: float, price: float, leverage: int, source: str = "unknown") -> Optional[TradeRecord]:
        """Log a completed trade to the database"""
        session = self.get_session()
        try:
            record = TradeRecord(
                symbol=symbol,
                side=side,
                size=size,
                price=price,
                leverage=leverage,
                notional_value=size * price,
                source=source,
                timestamp=datetime.utcnow()
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.debug(f"💾 Trade saved to DB: {record}")
            return record
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Failed to save trade to DB: {e}")
            return None
        finally:
            session.close()

    def get_recent_trades(self, limit: int = 50) -> List[TradeRecord]:
        """Fetch latest trades from DB"""
        session = self.get_session()
        try:
            return session.query(TradeRecord).order_by(TradeRecord.timestamp.desc()).limit(limit).all()
        finally:
            session.close()
