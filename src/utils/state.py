"""
State Persistence Module
=========================

Saves and restores bot state (active trades, daily P&L) so the bot
can survive restarts without losing track of open positions.
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger("state")

STATE_FILE = "data/bot_state.json"


def save_state(state: Dict[str, Any], filepath: str = STATE_FILE) -> bool:
    """
    Save bot state to JSON file.
    
    Args:
        state: Dictionary of state to persist
        filepath: Path to state file
        
    Returns:
        True if saved successfully
    """
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w") as f:
            json.dump(state, f, indent=2, default=str)

        logger.debug(f"State saved to {filepath}")
        return True
    except Exception as e:
        logger.error(f"Failed to save state: {e}")
        return False


def load_state(filepath: str = STATE_FILE) -> Optional[Dict[str, Any]]:
    """
    Load bot state from JSON file.
    
    Returns:
        State dict if file exists and is valid, None otherwise.
    """
    try:
        if not os.path.exists(filepath):
            logger.info("No previous state file found. Starting fresh.")
            return None

        with open(filepath, "r") as f:
            state = json.load(f)

        logger.info(f"State loaded from {filepath}")
        return state
    except Exception as e:
        logger.error(f"Failed to load state: {e}")
        return None


def clear_state(filepath: str = STATE_FILE) -> None:
    """Delete the state file."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info("State file cleared")
    except Exception as e:
        logger.error(f"Failed to clear state: {e}")
