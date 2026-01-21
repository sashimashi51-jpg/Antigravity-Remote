import os
import sys
import asyncio
import subprocess
import tempfile
import time
import logging
import json
from datetime import datetime
from typing import Dict, List

# Third-party dependencies
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode
    from telegram.ext import (
        ApplicationBuilder,
        ContextTypes,
        CommandHandler,
        CallbackQueryHandler,
        MessageHandler,
        filters,
    )
    import mss
    import pyautogui
    import pygetwindow as gw
    import psutil
    import pyperclip
    from PIL import Image
    import pytesseract
    # Set Tesseract path for Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    print("Missing dependencies. Run: pip install python-telegram-bot mss pyautogui pygetwindow psutil pyperclip pytesseract pillow")
    sys.exit(1)

# --- CONFIGURATION ---
bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "8587495609:AAHuNtyBPYU3OnYLOr-MDuuFFlVUznL6ncs")
allowed_user_id = os.getenv("TELEGRAM_USER_ID", "5014764185")
base_workspace_path = r"C:\Users\Kubrat\Documents\budeshtdoktor"

# Configure Logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

# --- STATE ---
class BotState:
    def __init__(self):
        self.paused = False
        self.locked = False
        self.lock_password = "unlock123"  # Change this!
        self.command_log: List[Dict] = []
        self.heartbeat_task = None
        self.watchdog_task = None
        self.watchdog_last_alert = 0  # Timestamp to avoid spam

state = BotState()

# --- AUTH ---
async def is_authorized(update: Update) -> bool:
    if str(update.effective_user.id) != str(allowed_user_id):
        return False
    return True

# --- WINDOW FUNCTIONS ---
def focus_antigravity():
    """Focus the Antigravity app window."""
    try:
        windows = gw.getWindowsWithTitle('Antigravity')
        if not windows:
            windows = gw.getWindowsWithTitle('Visual Studio Code')
        if not windows:
            windows = gw.getWindowsWithTitle('Cursor')
        if windows:
            win = windows[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.3)
            return True
    except Exception as e:
        logger.error(f"Error focusing window: {e}")
    return False

def send_to_antigravity(message: str):
    """Type the message into the Antigravity chat input."""
    try:
        if not focus_antigravity():
            return False
        
        time.sleep(0.3)
        screen_width, screen_height = pyautogui.size()
        
        # Click in the chat input area
        chat_input_x = int(screen_width * 0.75)
        chat_input_y = int(screen_height * 0.92)
        
        pyautogui.click(chat_input_x, chat_input_y)
        time.sleep(0.3)
        
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        
        pyperclip.copy(message)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)
        
        pyautogui.press('enter')
        return True
    except Exception as e:
        logger.error(f"Error sending to Antigravity: {e}")
        return False

def take_screenshot_sync() -> str:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=tmp.name)
            return tmp.name

# --- COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    
    help_text = """🔗 *Antigravity Remote Control*

*Relay:* Just send any message to relay it.

*Commands:*
`/status` - Screenshot now
`/pause` / `/resume` - Toggle relay
`/cancel` - Send Escape
`/scroll up|down` - Scroll chat
`/accept` / `/reject` - Click buttons
`/undo` - Ctrl+Z
`/sysinfo` - System stats
`/files` - List workspace files
`/read <file>` - Read a file
`/diff` - Git diff
`/log` - View command history
`/lock` / `/unlock <pwd>` - Lock bot
`/heartbeat <mins>` - Auto screenshots
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    msg = await update.message.reply_text("📸 Capturing...")
    path = await asyncio.to_thread(take_screenshot_sync)
    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(path, 'rb'), caption="🖥️ Current screen")
    os.remove(path)
    await msg.delete()

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    state.paused = True
    await update.message.reply_text("⏸️ Relay paused. Use /resume to continue.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    state.paused = False
    await update.message.reply_text("▶️ Relay resumed!")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    await asyncio.to_thread(lambda: (focus_antigravity(), pyautogui.press('escape')))
    await update.message.reply_text("❌ Sent Escape key")

async def scroll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    args = context.args
    direction = "down"
    multiplier = 1
    
    # Parse args: /scroll up x50 or /scroll down 10 or /scroll bottom
    for arg in args:
        if arg == "bottom":
            direction = "down"
            multiplier = 100  # Massive scroll to bottom
        elif arg == "top":
            direction = "up"
            multiplier = 100  # Massive scroll to top
        elif arg in ["up", "down"]:
            direction = arg
        elif arg.startswith("x") and arg[1:].isdigit():
            multiplier = int(arg[1:])
        elif arg.isdigit():
            multiplier = int(arg)
    
    # Base scroll amount * multiplier
    base_clicks = 25
    clicks = base_clicks * multiplier
    if direction == "down":
        clicks = -clicks  # Negative = scroll down (to latest)
    
    def do_scroll():
        focus_antigravity()
        screen_width, screen_height = pyautogui.size()
        chat_x = int(screen_width * 0.80)
        chat_y = int(screen_height * 0.40)
        pyautogui.moveTo(chat_x, chat_y)
        time.sleep(0.1)
        pyautogui.scroll(clicks)
    
    await asyncio.to_thread(do_scroll)
    await update.message.reply_text(f"📜 Scrolled {direction} x{multiplier}")

async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    await asyncio.to_thread(lambda: (focus_antigravity(), time.sleep(0.2), pyautogui.hotkey('alt', 'enter')))
    await update.message.reply_text("✅ Sent Accept (Alt+Enter)")

async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    await asyncio.to_thread(lambda: (focus_antigravity(), time.sleep(0.2), pyautogui.press('escape')))
    await update.message.reply_text("❌ Sent Reject (Escape)")

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    await asyncio.to_thread(lambda: (focus_antigravity(), pyautogui.hotkey('ctrl', 'z')))
    await update.message.reply_text("↩️ Sent Undo (Ctrl+Z)")

async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send any key combo: /key ctrl+s or /key alt+f4"""
    if not await is_authorized(update): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /key ctrl+s or /key alt+shift+tab")
        return
    
    combo = args[0].lower().split('+')
    
    def do_key():
        focus_antigravity()
        time.sleep(0.2)
        pyautogui.hotkey(*combo)
    
    await asyncio.to_thread(do_key)
    await update.message.reply_text(f"⌨️ Sent: `{'+'.join(combo)}`", parse_mode=ParseMode.MARKDOWN)

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule a command: /schedule 5m /status or /schedule 1h screenshot"""
    if not await is_authorized(update): return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /schedule 5m /status\nTime: 30s, 5m, 1h")
        return
    
    time_str = args[0].lower()
    scheduled_cmd = ' '.join(args[1:])
    
    # Parse time
    try:
        if time_str.endswith('s'):
            seconds = int(time_str[:-1])
        elif time_str.endswith('m'):
            seconds = int(time_str[:-1]) * 60
        elif time_str.endswith('h'):
            seconds = int(time_str[:-1]) * 3600
        else:
            seconds = int(time_str)
    except:
        await update.message.reply_text("Invalid time format. Use: 30s, 5m, 1h")
        return
    
    await update.message.reply_text(f"⏰ Scheduled `{scheduled_cmd}` in {time_str}", parse_mode=ParseMode.MARKDOWN)
    
    async def run_scheduled():
        await asyncio.sleep(seconds)
        # Take screenshot as the scheduled action
        if 'status' in scheduled_cmd.lower() or 'screenshot' in scheduled_cmd.lower():
            path = await asyncio.to_thread(take_screenshot_sync)
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=open(path, 'rb'),
                caption=f"⏰ Scheduled screenshot"
            )
            os.remove(path)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⏰ Timer complete for: {scheduled_cmd}"
            )
    
    asyncio.create_task(run_scheduled())

async def sysinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('C:/')
    msg = f"""⚙️ *System Info*
CPU: `{cpu}%`
RAM: `{mem.percent}%` ({mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB)
Disk C: `{disk.percent}%` ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    try:
        items = os.listdir(base_workspace_path)
        files = [f"📄 {i}" if os.path.isfile(os.path.join(base_workspace_path, i)) else f"📁 {i}" for i in items[:30]]
        await update.message.reply_text(f"📂 *Files in workspace:*\n" + "\n".join(files), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /read filename.txt")
        return
    filepath = os.path.join(base_workspace_path, args[0])
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()[:3000]
        await update.message.reply_text(f"📄 *{args[0]}*:\n```\n{content}\n```", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error reading file: {e}")

async def diff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    try:
        result = subprocess.run(['git', 'diff', '--stat'], cwd=base_workspace_path, capture_output=True, text=True, timeout=10)
        output = result.stdout[:3000] or "No changes"
        await update.message.reply_text(f"📊 *Git Diff:*\n```\n{output}\n```", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    if not state.command_log:
        await update.message.reply_text("📋 No commands logged yet.")
        return
    logs = state.command_log[-10:]
    log_text = "\n".join([f"`{l['time']}`: {l['msg'][:50]}" for l in logs])
    await update.message.reply_text(f"📋 *Recent Commands:*\n{log_text}", parse_mode=ParseMode.MARKDOWN)

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    state.locked = True
    await update.message.reply_text("🔒 Bot locked. Use /unlock <password> to unlock.")

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    args = context.args
    if args and args[0] == state.lock_password:
        state.locked = False
        await update.message.reply_text("🔓 Bot unlocked!")
    else:
        await update.message.reply_text("❌ Wrong password.")

async def heartbeat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    args = context.args
    
    if state.heartbeat_task:
        state.heartbeat_task.cancel()
        state.heartbeat_task = None
    
    if not args or args[0] == "off":
        await update.message.reply_text("💓 Heartbeat stopped.")
        return
    
    try:
        minutes = int(args[0])
    except:
        await update.message.reply_text("Usage: /heartbeat <minutes> or /heartbeat off")
        return
    
    async def heartbeat_loop():
        while True:
            await asyncio.sleep(minutes * 60)
            path = await asyncio.to_thread(take_screenshot_sync)
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(path, 'rb'), caption=f"💓 Heartbeat - {datetime.now().strftime('%H:%M')}")
            os.remove(path)
    
    state.heartbeat_task = asyncio.create_task(heartbeat_loop())
    await update.message.reply_text(f"💓 Heartbeat started! Screenshot every {minutes} minutes.")

async def watchdog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Monitor screen for approval dialogs and auto-screenshot."""
    if not await is_authorized(update): return
    args = context.args
    
    if state.watchdog_task:
        state.watchdog_task.cancel()
        state.watchdog_task = None
    
    if args and args[0] == "off":
        await update.message.reply_text("🐕 Watchdog stopped.")
        return
    
    # Keywords that indicate approval is needed
    approval_keywords = [
        "run command", "accept changes", "proceed", "approve", 
        "allow", "confirm", "yes or no", "y/n", "always allow",
        "do you want", "permission", "authorize"
    ]
    
    # Keywords that indicate task completion
    done_keywords = [
        "anything else", "let me know", "task complete", "done!",
        "successfully", "finished", "completed", "all set",
        "ready for", "is there anything"
    ]
    
    # Keywords that indicate errors
    error_keywords = [
        "error:", "failed", "exception", "traceback", "cannot",
        "permission denied", "not found", "invalid", "quota exceeded"
    ]
    
    check_interval = 5  # seconds
    last_screenshot_hash = None
    idle_count = 0
    
    async def watchdog_loop():
        nonlocal last_screenshot_hash, idle_count
        while True:
            await asyncio.sleep(check_interval)
            try:
                # Take screenshot and OCR it
                def scan_screen():
                    with mss.mss() as sct:
                        monitor = sct.monitors[1]
                        sct_img = sct.grab(monitor)
                        img = Image.frombytes('RGB', sct_img.size, sct_img.bgra, 'raw', 'BGRX')
                        text = pytesseract.image_to_string(img).lower()
                        # Simple hash for activity detection
                        img_hash = hash(img.tobytes()[:10000])
                        return text, img_hash
                
                screen_text, current_hash = await asyncio.to_thread(scan_screen)
                current_time = time.time()
                
                # Activity monitoring - if screen unchanged for 2 cycles
                if current_hash == last_screenshot_hash:
                    idle_count += 1
                else:
                    idle_count = 0
                last_screenshot_hash = current_hash
                
                # Check for approval keywords (highest priority)
                for keyword in approval_keywords:
                    if keyword in screen_text:
                        if current_time - state.watchdog_last_alert > 30:
                            state.watchdog_last_alert = current_time
                            path = await asyncio.to_thread(take_screenshot_sync)
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=open(path, 'rb'),
                                caption=f"🚨 *Approval needed!*\nDetected: `{keyword}`",
                                parse_mode=ParseMode.MARKDOWN
                            )
                            os.remove(path)
                        break
                
                # Check for done keywords
                for keyword in done_keywords:
                    if keyword in screen_text:
                        if current_time - state.watchdog_last_alert > 30:
                            state.watchdog_last_alert = current_time
                            path = await asyncio.to_thread(take_screenshot_sync)
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=open(path, 'rb'),
                                caption=f"✅ *Task appears complete!*\nDetected: `{keyword}`",
                                parse_mode=ParseMode.MARKDOWN
                            )
                            os.remove(path)
                        break
                
                # Check for error keywords
                for keyword in error_keywords:
                    if keyword in screen_text:
                        if current_time - state.watchdog_last_alert > 30:
                            state.watchdog_last_alert = current_time
                            path = await asyncio.to_thread(take_screenshot_sync)
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=open(path, 'rb'),
                                caption=f"⚠️ *Error detected!*\nDetected: `{keyword}`",
                                parse_mode=ParseMode.MARKDOWN
                            )
                            os.remove(path)
                        break
                
                # Activity monitor - idle for 2+ cycles (10+ seconds of no change)
                if idle_count >= 2 and current_time - state.watchdog_last_alert > 60:
                    state.watchdog_last_alert = current_time
                    idle_count = 0
                    path = await asyncio.to_thread(take_screenshot_sync)
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=open(path, 'rb'),
                        caption=f"💤 *Screen idle* - No activity detected",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    os.remove(path)
                    
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
    
    state.watchdog_task = asyncio.create_task(watchdog_loop())
    await update.message.reply_text(
        "🐕 *Watchdog started!*\n\n"
        "I'll alert you when:\n"
        "• 🚨 Approval is needed\n"
        "• ✅ Task appears complete\n"
        "• ⚠️ Errors are detected\n"
        "• 💤 Screen goes idle\n\n"
        "Use `/watchdog off` to stop.",
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update): return
    
    if state.locked:
        await update.message.reply_text("🔒 Bot is locked. Use /unlock <password>")
        return
    
    if state.paused:
        await update.message.reply_text("⏸️ Relay is paused. Use /resume")
        return
    
    user_msg = update.message.text
    
    # Log command
    state.command_log.append({"time": datetime.now().strftime("%H:%M:%S"), "msg": user_msg})
    if len(state.command_log) > 100:
        state.command_log = state.command_log[-50:]
    
    status_msg = await update.message.reply_text("📤 Sending to Antigravity...")
    success = await asyncio.to_thread(send_to_antigravity, user_msg)
    
    if not success:
        await status_msg.edit_text("❌ Failed to send. Is Antigravity app open?")
        return
    
    keyboard = [[InlineKeyboardButton("📸 Get Result", callback_data="screenshot")]]
    await status_msg.edit_text(
        "✅ *Sent!* Tap when ready:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available models and let user switch."""
    if not await is_authorized(update): return
    
    # Available models in Antigravity
    models = [
        ("Gemini 3 Pro (High)", "gemini_3_pro_high"),
        ("Gemini 3 Pro (Low)", "gemini_3_pro_low"),
        ("Gemini 3 Flash", "gemini_3_flash"),
        ("Claude Sonnet 4.5", "claude_sonnet_45"),
        ("Claude Sonnet 4.5 (Thinking)", "claude_sonnet_45_thinking"),
        ("Claude Opus 4.5 (Thinking)", "claude_opus_45_thinking"),
        ("GPT-OSS 120B (Medium)", "gpt_oss_120b"),
    ]
    
    keyboard = []
    for display_name, model_id in models:
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"model_{model_id}")])
    
    await update.message.reply_text(
        "🤖 *Select a model:*\n\n_Note: Model availability depends on your Antigravity subscription_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_authorized(update): return
    
    if query.data == "screenshot":
        await query.message.reply_text("📸 Capturing...")
        path = await asyncio.to_thread(take_screenshot_sync)
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(path, 'rb'))
        os.remove(path)
    
    elif query.data.startswith("model_"):
        model_id = query.data.replace("model_", "")
        model_names = {
            "gemini_3_pro_high": "Gemini 3 Pro (High)",
            "gemini_3_pro_low": "Gemini 3 Pro (Low)",
            "gemini_3_flash": "Gemini 3 Flash",
            "claude_sonnet_45": "Claude Sonnet 4.5",
            "claude_sonnet_45_thinking": "Claude Sonnet 4.5 (Thinking)",
            "claude_opus_45_thinking": "Claude Opus 4.5 (Thinking)",
            "gpt_oss_120b": "GPT-OSS 120B (Medium)",
        }
        model_name = model_names.get(model_id, model_id)
        
        # Use keyboard shortcut to open model selector (Ctrl+Shift+P in VS Code)
        def switch_model():
            focus_antigravity()
            time.sleep(0.2)
            # Open command palette
            pyautogui.hotkey('ctrl', 'shift', 'p')
            time.sleep(0.5)
            # Type model switch command
            pyperclip.copy(f"Switch Model")
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.3)
            pyautogui.press('enter')
            time.sleep(0.3)
            # Type model name
            pyperclip.copy(model_name)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.2)
            pyautogui.press('enter')
        
        await asyncio.to_thread(switch_model)
        await query.message.reply_text(f"🔄 Switching to *{model_name}*...", parse_mode=ParseMode.MARKDOWN)
    
    # Quick reply actions
    elif query.data.startswith("quick_"):
        action = query.data.replace("quick_", "")
        action_map = {
            "yes": "Yes",
            "no": "No",
            "proceed": "Proceed",
            "cancel": "Cancel",
            "approve": "Approve",
            "skip": "Skip"
        }
        text = action_map.get(action, action.capitalize())
        success = await asyncio.to_thread(send_to_antigravity, text)
        if success:
            await query.message.reply_text(f"📤 Sent: *{text}*", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.message.reply_text("❌ Failed to send")

async def quick_replies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show quick reply buttons."""
    if not await is_authorized(update): return
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes", callback_data="quick_yes"),
         InlineKeyboardButton("❌ No", callback_data="quick_no")],
        [InlineKeyboardButton("▶️ Proceed", callback_data="quick_proceed"),
         InlineKeyboardButton("⏹️ Cancel", callback_data="quick_cancel")],
        [InlineKeyboardButton("👍 Approve", callback_data="quick_approve"),
         InlineKeyboardButton("⏭️ Skip", callback_data="quick_skip")],
    ]
    
    await update.message.reply_text(
        "⚡ *Quick Replies* - Tap to send:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask Antigravity to summarize what it did."""
    if not await is_authorized(update): return
    
    summary_prompt = "Please give me a brief summary of what you just did in the last task."
    
    status_msg = await update.message.reply_text("📝 Asking for summary...")
    success = await asyncio.to_thread(send_to_antigravity, summary_prompt)
    
    if success:
        keyboard = [[InlineKeyboardButton("📸 Get Summary", callback_data="screenshot")]]
        await status_msg.edit_text(
            "📝 *Summary requested!*\nWait a moment for the response, then tap:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await status_msg.edit_text("❌ Failed to send summary request")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages - download, transcribe, and relay."""
    if not await is_authorized(update): return
    
    voice = update.message.voice
    status_msg = await update.message.reply_text("🎤 Processing voice message...")
    
    try:
        # Download voice file
        file = await context.bot.get_file(voice.file_id)
        voice_path = os.path.join(tempfile.gettempdir(), f"voice_{voice.file_id}.ogg")
        await file.download_to_drive(voice_path)
        
        # Try to transcribe with speech recognition
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            
            # Convert ogg to wav
            wav_path = voice_path.replace('.ogg', '.wav')
            os.system(f'ffmpeg -i "{voice_path}" -y "{wav_path}" 2>/dev/null')
            
            with sr.AudioFile(wav_path) as source:
                audio = recognizer.record(source)
                text = recognizer.recognize_google(audio)
            
            os.remove(wav_path)
            os.remove(voice_path)
            
            # Relay transcribed text
            await status_msg.edit_text(f"🎤 Transcribed: *{text}*\n\nSending...", parse_mode=ParseMode.MARKDOWN)
            success = await asyncio.to_thread(send_to_antigravity, text)
            
            if success:
                keyboard = [[InlineKeyboardButton("📸 Get Result", callback_data="screenshot")]]
                await status_msg.edit_text(
                    f"✅ *Voice relayed:*\n`{text}`",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await status_msg.edit_text("❌ Failed to relay voice message")
                
        except ImportError:
            await status_msg.edit_text("⚠️ Voice transcription not available.\nInstall: `pip install SpeechRecognition`", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Transcription failed: {e}")
            os.remove(voice_path)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error processing voice: {e}")

def main():
    if bot_token == "YOUR_BOT_TOKEN_HERE":
        print("Error: Set TELEGRAM_BOT_TOKEN")
        return

    application = ApplicationBuilder().token(bot_token).build()

    # Register all handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("scroll", scroll_command))
    application.add_handler(CommandHandler("accept", accept_command))
    application.add_handler(CommandHandler("reject", reject_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(CommandHandler("sysinfo", sysinfo_command))
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("read", read_command))
    application.add_handler(CommandHandler("diff", diff_command))
    application.add_handler(CommandHandler("log", log_command))
    application.add_handler(CommandHandler("lock", lock_command))
    application.add_handler(CommandHandler("unlock", unlock_command))
    application.add_handler(CommandHandler("heartbeat", heartbeat_command))
    application.add_handler(CommandHandler("key", key_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("watchdog", watchdog_command))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CommandHandler("quick", quick_replies_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 Antigravity Remote Control - FULL VERSION")
    print(f"   User: {allowed_user_id}")
    print(f"   Lock password: {state.lock_password}")
    application.run_polling()

if __name__ == '__main__':
    main()
