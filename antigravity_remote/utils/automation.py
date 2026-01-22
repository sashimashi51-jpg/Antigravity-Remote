"""Window automation utilities for Antigravity Remote."""

import logging
import time
from typing import Optional

import pyautogui
import pygetwindow as gw
import pyperclip

logger = logging.getLogger(__name__)

# Configure pyautogui safety settings
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1


def focus_antigravity() -> bool:
    """
    Focus the Antigravity/VS Code/Cursor window.
    
    Returns:
        True if window was focused, False otherwise.
    """
    try:
        # Try different window titles in priority order
        window_titles = ['Antigravity IDE', 'Antigravity', 'Visual Studio Code', 'Cursor']
        
        for title in window_titles:
            windows = gw.getWindowsWithTitle(title)
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                time.sleep(0.3)
                return True
                
        logger.warning("No Antigravity/VS Code/Cursor window found")
        return False
        
    except Exception as e:
        logger.error(f"Error focusing window: {e}")
        return False


def send_to_antigravity(message: str) -> bool:
    """
    Send a message to the Antigravity chat input.
    
    Args:
        message: The message to send.
        
    Returns:
        True if message was sent, False otherwise.
    """
    try:
        if not focus_antigravity():
            return False
        
        time.sleep(0.3)
        screen_width, screen_height = pyautogui.size()
        
        # Click in the chat input area (right side, near bottom)
        chat_input_x = int(screen_width * 0.75)
        chat_input_y = int(screen_height * 0.92)
        
        pyautogui.click(chat_input_x, chat_input_y)
        time.sleep(0.3)
        
        # Select all and paste new message
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        
        pyperclip.copy(message)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)
        
        # Send message
        pyautogui.press('enter')
        
        logger.info(f"Sent message to Antigravity: {message[:50]}...")
        return True
        
    except Exception as e:
        logger.error(f"Error sending to Antigravity: {e}")
        return False


def send_key_combo(keys: list[str]) -> bool:
    """
    Send a keyboard shortcut.
    
    Args:
        keys: List of keys to press together (e.g., ['ctrl', 's']).
        
    Returns:
        True if keys were sent, False otherwise.
    """
    try:
        if not focus_antigravity():
            return False
        
        time.sleep(0.2)
        pyautogui.hotkey(*keys)
        logger.info(f"Sent key combo: {'+'.join(keys)}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending key combo: {e}")
        return False


def scroll_screen(clicks: int, x_percent: float = 0.80, y_percent: float = 0.40) -> bool:
    """
    Scroll the screen at specified position.
    
    Args:
        clicks: Number of scroll clicks (positive = up, negative = down).
        x_percent: Horizontal position as percentage of screen width.
        y_percent: Vertical position as percentage of screen height.
        
    Returns:
        True if scroll was performed, False otherwise.
    """
    try:
        if not focus_antigravity():
            return False
        
        screen_width, screen_height = pyautogui.size()
        x = int(screen_width * x_percent)
        y = int(screen_height * y_percent)
        
        pyautogui.moveTo(x, y)
        time.sleep(0.1)
        pyautogui.scroll(clicks)
        
        logger.info(f"Scrolled {clicks} clicks at ({x}, {y})")
        return True
        
    except Exception as e:
        logger.error(f"Error scrolling: {e}")
        return False
