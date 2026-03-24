import sys
import collections
from pathlib import Path
from loguru import logger

# Global log buffer for Web UI
log_buffer = collections.deque(maxlen=200)

# Add custom levels
try:
    logger.level("TRACK", no=21, color="<magenta>", icon="🐋")
except ValueError:
    pass # Already exists

def custom_sink(message):
    log_buffer.append(message.strip())

def setup_logger(log_file: str = "./logs/trading.log", log_level: str = "INFO"):
    """
    Setup loguru logger with file and console output
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove default handler
    logger.remove()
    
    # Add console handler with colors
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True
    )
    
    # Add file handler
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        level=log_level,
        rotation="100 MB",
        retention="30 days",
        compression="zip"
    )
    
    # Add memory sink for UI
    logger.add(
        custom_sink,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        level=log_level,
        colorize=False
    )
    
    return logger
