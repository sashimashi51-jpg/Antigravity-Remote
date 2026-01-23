# Antigravity Remote 🚀

Remote control your [Antigravity](https://antigravity.dev) AI assistant via Telegram.

[![Telegram Bot](https://img.shields.io/badge/Telegram-@antigravityrcbot-blue?logo=telegram)](https://t.me/antigravityrcbot)
[![PyPI](https://img.shields.io/pypi/v/antigravity-remote)](https://pypi.org/project/antigravity-remote/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- 📱 **Message Relay** - Send instructions from your phone
- 📸 **Screenshots** - View screen anytime
- ⚡ **Quick Replies** - One-tap Yes/No/Proceed buttons
- 🔐 **Secure** - Your data never leaves your PC

## Quick Start

### 1. Install

```bash
pip install antigravity-remote
```

### 2. Register

```bash
antigravity-remote --register
```

Enter your Telegram User ID (get it from [@userinfobot](https://t.me/userinfobot)).

### 3. Run

```bash
antigravity-remote
```

### 4. Control from Telegram

👉 **[@antigravityrcbot](https://t.me/antigravityrcbot)**

## Requirements

- Python 3.10+
- Windows

## Commands (in Telegram)

### 🎮 Live Control
| Command | Description |
|---------|-------------|
| `/stream` | Start real-time WebSocket stream |
| `/status` or `/ss` | Take a high-quality screenshot |
| `/scroll up/down` | Scroll the active window |
| `/accept` / `/reject` | Quick AI approval buttons |

### 🧠 AI & Code
| Command | Description |
|---------|-------------|
| `Any text` | Relay instruction to AI agent |
| `/diff` | Preview pending code changes |
| `/undo N` | Revert last N changes |
| `/tts` | Read AI response aloud (TTS) |

### ⚙️ Automation & Settings
| Command | Description |
|---------|-------------|
| `/schedule 9:00 cmd` | Automate a task at a specific time |
| `/watchdog on/off` | Alerts when AI stops or needs input |
| `/quick` | Show action button keyboard |
| `/model` | Switch between AI models |
| `/pause` / `/resume` | Temporary pause/resume agent |

## How It Works

```
📱 Your Phone        ☁️ Server          💻 Your PC
      │ Message bot       │                   │
      ├──────────────────►│                   │
      │                   │ WebSocket         │
      │                   ├──────────────────►│
      │                   │                   │ Execute
      │                   │◄──────────────────┤ Screenshot
      │◄──────────────────┤                   │
```

Your bot token stays on our secure server. You only run a lightweight agent on your PC.

## License

MIT © Kubrat
