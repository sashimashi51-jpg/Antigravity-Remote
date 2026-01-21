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

| Command | Description |
|---------|-------------|
| `/status` | Take screenshot |
| `/scroll up/down` | Scroll chat |
| `/accept` / `/reject` | Accept/reject |
| `/key ctrl+s` | Send key combo |
| `/quick` | Quick reply buttons |
| Any text | Relay to Antigravity |

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
