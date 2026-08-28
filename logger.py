import logging
import os
from datetime import datetime
from typing import Optional

def setup_logger(
    name: str = __name__,
    log_level: int = logging.INFO,
    log_dir: str = "logs",
    console_output: bool = True
) -> logging.Logger:
    """
    Set up a logger with day-wise log files and optional console output.
    
    Args:
        name: Logger name (typically __name__ from calling module)
        log_level: Logging level (default: INFO)
        log_dir: Directory to store log files (default: "logs")
        console_output: Whether to output to console (default: True)
    
    Returns:
        Configured logger instance
    """
    # Create logs directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)
    
    # Generate today's log filename
    today = datetime.now().strftime("%Y-%m-%d")
    log_filename = os.path.join(log_dir, f"borges_{today}.log")
    
    # Create logger
    logger = logging.getLogger(name)
    
    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Set logging level
    logger.setLevel(log_level)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # File handler for day-wise logs
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)
    
    # Console handler (optional)
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    return logger

def get_logger(name: str = __name__) -> logging.Logger:
    """
    Get an existing logger or create a new one with default settings.
    
    Args:
        name: Logger name (typically __name__ from calling module)
    
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    
    # If logger has no handlers, set it up with defaults
    if not logger.handlers:
        return setup_logger(name)
    
    return logger