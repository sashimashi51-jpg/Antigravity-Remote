"""
Antigravity Remote - API Routes
REST endpoints and WebSocket streaming for the FastAPI application.
"""

import asyncio
import base64
import io
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# These will be injected by app.py
connected_clients = None
live_stream = None
send_cmd = None
stream_viewers = {}  # user_id -> list of viewer WebSockets


def init_routes(clients_ref, live_stream_ref, send_cmd_func):
    """Initialize routes with shared state."""
    global connected_clients, live_stream, send_cmd
    connected_clients = clients_ref
    live_stream = live_stream_ref
    send_cmd = send_cmd_func


@router.get("/")
async def root():
    """Root endpoint - server status."""
    return {
        "status": "online",
        "version": "4.6.0",
        "clients": len(connected_clients) if connected_clients else 0,
        "features": ["h264_stream", "telemetry", "two_way_chat", "watchdog"]
    }


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# Global telemetry store
telemetry_data = {}  # user_id -> latest telemetry dict

@router.get("/stream/{user_id}")
async def stream_page(user_id: str):
    """Nerd-Edition HTML page for real-time H.264 video and telemetry."""
    host = os.environ.get("RENDER_EXTERNAL_URL", "")
    if host:
        ws_host = host.replace("https://", "wss://").replace("http://", "ws://")
    else:
        port = os.environ.get("PORT", 10000)
        ws_host = f"ws://localhost:{port}"
    
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Antigravity Nerd Control</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ 
                background: #0a0a12;
                color: #e0e0e0; 
                font-family: 'Fira Code', 'Cascadia Code', monospace;
                display: grid;
                grid-template-columns: 1fr 300px;
                height: 100vh;
                overflow: hidden;
            }}
            .main-content {{ padding: 20px; display: flex; flex-direction: column; gap: 15px; overflow-y: auto; }}
            .sidebar {{ 
                background: #121220; 
                border-left: 1px solid #333; 
                padding: 20px; 
                display: flex; 
                flex-direction: column; 
                gap: 20px;
                overflow-y: auto;
            }}
            .header {{ display: flex; align-items: center; justify-content: space-between; }}
            h1 {{ color: #00d4ff; font-size: 1.2rem; }}
            .live-badge {{ background: #ff3b3b; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: bold; }}
            
            .stream-container {{
                background: #000;
                border: 1px solid #00d4ff33;
                border-radius: 8px;
                position: relative;
                width: 100%;
                aspect-ratio: 16/9;
            }}
            #videoPlayer {{ width: 100%; height: 100%; border-radius: 7px; object-fit: contain; }}
            
            .card {{ background: #1a1a2e; border: 1px solid #333; padding: 12px; border-radius: 6px; }}
            .card-title {{ color: #00d4ff; font-size: 0.8rem; text-transform: uppercase; margin-bottom: 8px; display: flex; align-items: center; gap: 5px; }}
            .metric-val {{ font-size: 1.2rem; font-weight: bold; }}
            
            .controls {{ display: flex; gap: 8px; flex-wrap: wrap; }}
            button {{ 
                background: #252545; color: #fff; border: 1px solid #444; padding: 8px 12px; border-radius: 4px; 
                font-size: 0.8rem; cursor: pointer; transition: all 0.2s;
            }}
            button:hover {{ background: #00d4ff; color: #000; border-color: #00d4ff; }}
            
            .log-container {{ flex-grow: 1; min-height: 0; display: flex; flex-direction: column; }}
            #logs {{ background: #000; padding: 10px; border-radius: 4px; font-size: 0.7rem; color: #00ff00; overflow-y: auto; flex-grow: 1; border: 1px solid #333; line-height: 1.4; }}
            .log-entry {{ margin-bottom: 4px; }}
            .log-time {{ color: #888; margin-right: 5px; }}
            
            @media (max-width: 900px) {{
                body {{ grid-template-columns: 1fr; overflow-y: auto; }}
                .sidebar {{ border-left: none; border-top: 1px solid #333; min-height: 400px; }}
            }}
        </style>
    </head>
    <body>
        <div class="main-content">
            <div class="header">
                <h1>🔮 ANTIGRAVITY MISSION CONTROL</h1>
                <span class="live-badge" id="liveBadge">H.264 LIVE</span>
            </div>
            
            <div class="stream-container">
                <video id="videoPlayer" autoplay muted playsinline></video>
                <div style="position: absolute; top: 10px; right: 10px; display: flex; gap: 10px;">
                    <span id="fps" class="metric-val" style="font-size: 0.8rem; background: rgba(0,0,0,0.5); padding: 4px 8px; border-radius: 4px;">-- FPS</span>
                </div>
            </div>
            
            <div class="controls">
                <button onclick="sendCommand('accept')">ACCEPT</button>
                <button onclick="sendCommand('reject')">REJECT</button>
                <button onclick="sendCommand('scroll_up')">SCROLL UP</button>
                <button onclick="sendCommand('scroll_down')">SCROLL DOWN</button>
                <button onclick="sendCommand('screenshot')">SNAPSHOT</button>
            </div>
            
            <div class="card">
                <div class="card-title">📡 CURRENT STATUS</div>
                <div id="agentStatus" class="metric-val">INITIALIZING...</div>
            </div>
        </div>
        
        <div class="sidebar">
            <div class="card">
                <div class="card-title">💾 SYSTEM METRICS</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div>
                        <div style="font-size: 0.6rem; color: #888;">CPU</div>
                        <div id="cpuMetric" class="metric-val">--%</div>
                    </div>
                    <div>
                        <div style="font-size: 0.6rem; color: #888;">RAM</div>
                        <div id="ramMetric" class="metric-val">--%</div>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-title">🔧 ACTIVE PROCESS</div>
                <div id="processMetric" class="metric-val" style="font-size: 1rem; color: #ffaa00;">-</div>
            </div>
            
            <div class="log-container">
                <div class="card-title">📄 TELEMETRY LOG</div>
                <div id="logs"></div>
            </div>
        </div>
        
        <script>
            const video = document.getElementById('videoPlayer');
            const wsUrl = '{ws_host}/stream/{user_id}/ws';
            let ws = null;
            let mediaSource = null;
            let sourceBuffer = null;
            let queue = [];
            
            function addLog(msg) {{
                const logs = document.getElementById('logs');
                const entry = document.createElement('div');
                entry.className = 'log-entry';
                const time = new Date().toLocaleTimeString();
                entry.innerHTML = `<span class="log-time">[${{time}}]</span> ${{msg}}`;
                logs.prepend(entry);
                if (logs.childNodes.length > 50) logs.removeChild(logs.lastChild);
            }}

            function initMSE() {{
                mediaSource = new MediaSource();
                video.src = URL.createObjectURL(mediaSource);
                mediaSource.addEventListener('sourceopen', () => {{
                    sourceBuffer = mediaSource.addSourceBuffer('video/mp4; codecs="avc1.42E01E"');
                    sourceBuffer.mode = 'sequence';
                    sourceBuffer.addEventListener('updateend', () => {{
                        if (queue.length > 0 && !sourceBuffer.updating) {{
                            sourceBuffer.appendBuffer(queue.shift());
                        }}
                    }});
                }});
            }}

            function connect() {{
                addLog('Attempting WebSocket handshake...');
                ws = new WebSocket(wsUrl);
                ws.binaryType = 'arraybuffer';
                
                ws.onopen = () => addLog('Connected to bridge server.');
                
                ws.onmessage = async (event) => {{
                    if (typeof event.data === 'string') {{
                        try {{
                            const msg = JSON.parse(event.data);
                            if (msg.type === 'telemetry') {{
                                const data = msg.data;
                                document.getElementById('cpuMetric').textContent = data.cpu.toFixed(1) + '%';
                                document.getElementById('ramMetric').textContent = data.ram.toFixed(1) + '%';
                                document.getElementById('processMetric').textContent = data.process;
                                document.getElementById('agentStatus').textContent = data.agent_status.toUpperCase();
                                if (data.process !== 'Idle') addLog('Active process: ' + data.process);
                            }}
                        }} catch(e) {{}}
                    }} else {{
                        // Binary video chunk
                        if (sourceBuffer && !sourceBuffer.updating) {{
                            sourceBuffer.appendBuffer(new Uint8Array(event.data));
                        }} else {{
                            queue.push(new Uint8Array(event.data));
                        }}
                    }}
                }};
                
                ws.onclose = () => {{
                    addLog('Connection lost. Retrying...');
                    setTimeout(connect, 2000);
                }};
            }}

            function sendCommand(cmd) {{
                if (ws && ws.readyState === 1) {{
                    ws.send(JSON.stringify({{command: cmd}}));
                    addLog('Sent command: ' + cmd.toUpperCase());
                }}
            }}
            
            initMSE();
            connect();
        </script>
    </body>
    </html>
    """)


@router.websocket("/stream/{user_id}/ws")
async def stream_websocket(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for 'Nerd Edition' H.264 and Telemetry relay."""
    await websocket.accept()
    
    if user_id not in stream_viewers:
        stream_viewers[user_id] = []
    stream_viewers[user_id].append(websocket)
    
    logger.info(f"📡 Nerd viewer connected for {user_id[-4:]}")

    async def receive_and_relay():
        try:
            while True:
                data = await websocket.receive()
                
                if "bytes" in data:
                    # Relay H.264 binary chunks
                    await broadcast_to_viewers(user_id, data["bytes"])
                elif "text" in data:
                    try:
                        msg = json.loads(data["text"])
                        if msg.get("type") == "telemetry":
                            telemetry_data[user_id] = msg["data"]
                            await broadcast_to_viewers(user_id, data["text"])
                        elif msg.get("command"):
                            cmd_type = msg["command"]
                            if send_cmd:
                                agent_cmd = {"type": cmd_type}
                                if cmd_type == "scroll_up": agent_cmd = {"type": "scroll", "direction": "up"}
                                elif cmd_type == "scroll_down": agent_cmd = {"type": "scroll", "direction": "down"}
                                await send_cmd(user_id, agent_cmd)
                    except json.JSONDecodeError:
                        pass
                            
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Relay error: {e}")

    try:
        await receive_and_relay()
    finally:
        if user_id in stream_viewers:
            stream_viewers[user_id] = [v for v in stream_viewers[user_id] if v != websocket]
        logger.info(f"📡 Nerd viewer disconnected for {user_id[-4:]}")


async def broadcast_to_viewers(user_id: str, data: any):
    """Broadcast binary chunks or JSON text to all viewers of a stream."""
    if user_id in stream_viewers:
        dead_viewers = []
        for viewer in stream_viewers[user_id]:
            try:
                if isinstance(data, bytes):
                    await viewer.send_bytes(data)
                else:
                    await viewer.send_text(data)
            except:
                dead_viewers.append(viewer)
        
        for dead in dead_viewers:
            stream_viewers[user_id].remove(dead)

