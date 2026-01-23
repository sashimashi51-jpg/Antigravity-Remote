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
stream_viewers = {}  # user_id -> list of viewer WebSockets


def init_routes(clients_ref, live_stream_ref):
    """Initialize routes with shared state."""
    global connected_clients, live_stream
    connected_clients = clients_ref
    live_stream = live_stream_ref


@router.get("/")
async def root():
    """Root endpoint - server status."""
    return {
        "status": "online",
        "version": "4.5.0",
        "clients": len(connected_clients) if connected_clients else 0,
        "features": ["realtime_stream", "two_way_chat", "scheduled_tasks", "undo_stack", "progress_bar"]
    }


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/stream/{user_id}")
async def stream_page(user_id: str):
    """HTML page for real-time WebSocket streaming."""
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
        <title>Antigravity Live Stream</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ 
                background: linear-gradient(135deg, #0d0d1a 0%, #1a1a2e 100%);
                color: white; 
                font-family: 'Segoe UI', system-ui, sans-serif;
                min-height: 100vh;
                padding: 15px;
            }}
            .header {{
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 15px;
            }}
            h1 {{ 
                color: #00d4ff; 
                font-size: 1.5rem;
                font-weight: 600;
            }}
            .live-badge {{
                background: #ff3b3b;
                color: white;
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 0.75rem;
                font-weight: bold;
                animation: pulse 1.5s infinite;
            }}
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.6; }}
            }}
            .stream-container {{
                position: relative;
                border-radius: 12px;
                overflow: hidden;
                background: #000;
                box-shadow: 0 10px 40px rgba(0, 212, 255, 0.2);
            }}
            #stream {{ 
                width: 100%;
                display: block;
            }}
            .overlay {{
                position: absolute;
                top: 10px;
                right: 10px;
                display: flex;
                gap: 8px;
            }}
            .stat {{
                background: rgba(0,0,0,0.7);
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 0.8rem;
            }}
            .controls {{
                display: flex;
                gap: 10px;
                margin-top: 15px;
                flex-wrap: wrap;
            }}
            button {{
                background: linear-gradient(135deg, #00d4ff, #0099cc);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.1s;
            }}
            button:hover {{ transform: scale(1.02); }}
            button:active {{ transform: scale(0.98); }}
            button.danger {{ background: linear-gradient(135deg, #ff4444, #cc0000); }}
            .status-bar {{
                margin-top: 15px;
                padding: 12px;
                background: rgba(255,255,255,0.05);
                border-radius: 8px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .status {{ color: #00ff88; font-weight: 600; }}
            .status.error {{ color: #ff4444; }}
            .status.connecting {{ color: #ffaa00; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🔮 Antigravity Remote</h1>
            <span class="live-badge" id="liveBadge">● LIVE</span>
        </div>
        
        <div class="stream-container">
            <img id="stream" src="" alt="Connecting...">
            <div class="overlay">
                <span class="stat" id="fps">-- FPS</span>
                <span class="stat" id="latency">-- ms</span>
            </div>
        </div>
        
        <div class="controls">
            <button onclick="sendCommand('accept')">✅ Accept</button>
            <button onclick="sendCommand('reject')" class="danger">❌ Reject</button>
            <button onclick="sendCommand('screenshot')">📸 Screenshot</button>
            <button onclick="sendCommand('scroll_up')">⬆️ Up</button>
            <button onclick="sendCommand('scroll_down')">⬇️ Down</button>
        </div>
        
        <div class="status-bar">
            <span>Stream: <span class="status" id="status">Connecting...</span></span>
            <span id="frames">0 frames</span>
        </div>
        
        <script>
            const userId = '{user_id}';
            const wsUrl = '{ws_host}/stream/{user_id}/ws';
            const img = document.getElementById('stream');
            const status = document.getElementById('status');
            const fpsEl = document.getElementById('fps');
            const latencyEl = document.getElementById('latency');
            const framesEl = document.getElementById('frames');
            const liveBadge = document.getElementById('liveBadge');
            
            let ws = null;
            let frameCount = 0;
            let lastFrameTime = Date.now();
            let fpsCounter = [];
            
            function connect() {{
                status.textContent = 'Connecting...';
                status.className = 'status connecting';
                
                ws = new WebSocket(wsUrl);
                
                ws.onopen = () => {{
                    status.textContent = 'Connected';
                    status.className = 'status';
                    liveBadge.style.display = 'inline';
                }};
                
                ws.onmessage = (event) => {{
                    const now = Date.now();
                    
                    // Calculate FPS
                    fpsCounter.push(now);
                    fpsCounter = fpsCounter.filter(t => now - t < 1000);
                    fpsEl.textContent = fpsCounter.length + ' FPS';
                    
                    // Calculate latency (approximate)
                    const latency = now - lastFrameTime;
                    latencyEl.textContent = latency + ' ms';
                    lastFrameTime = now;
                    
                    // Update frame
                    img.src = 'data:image/jpeg;base64,' + event.data;
                    frameCount++;
                    framesEl.textContent = frameCount + ' frames';
                }};
                
                ws.onclose = () => {{
                    status.textContent = 'Disconnected';
                    status.className = 'status error';
                    liveBadge.style.display = 'none';
                    setTimeout(connect, 2000);
                }};
                
                ws.onerror = () => {{
                    status.textContent = 'Error';
                    status.className = 'status error';
                }};
            }}
            
            function sendCommand(cmd) {{
                if (ws && ws.readyState === WebSocket.OPEN) {{
                    ws.send(JSON.stringify({{command: cmd}}));
                }}
            }}
            
            connect();
        </script>
    </body>
    </html>
    """)


@router.websocket("/stream/{user_id}/ws")
async def stream_websocket(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for real-time screen streaming."""
    await websocket.accept()
    
    # Add viewer to list
    if user_id not in stream_viewers:
        stream_viewers[user_id] = []
    stream_viewers[user_id].append(websocket)
    
    logger.info(f"📺 Stream viewer connected for user {user_id[-4:]}")
    
    try:
        # Send frames as they come in
        while True:
            if live_stream:
                frame = live_stream.get_frame(user_id)
                if frame:
                    # Send as base64
                    frame_b64 = base64.b64encode(frame).decode()
                    await websocket.send_text(frame_b64)
            
            # Check for commands from viewer
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                # Handle viewer commands (accept, reject, etc.)
                logger.info(f"Viewer command: {data}")
            except asyncio.TimeoutError:
                pass
            
            await asyncio.sleep(0.1)  # ~10 FPS max polling
            
    except WebSocketDisconnect:
        logger.info(f"📺 Stream viewer disconnected for user {user_id[-4:]}")
    except Exception as e:
        logger.error(f"Stream WebSocket error: {e}")
    finally:
        if user_id in stream_viewers:
            stream_viewers[user_id] = [v for v in stream_viewers[user_id] if v != websocket]


@router.get("/stream/{user_id}/frame")
async def stream_frame(user_id: str):
    """Get latest frame (fallback for polling)."""
    if live_stream:
        frame = live_stream.get_frame(user_id)
        if frame:
            return StreamingResponse(io.BytesIO(frame), media_type="image/jpeg")
    return JSONResponse({"error": "No stream"}, status_code=404)


async def broadcast_frame(user_id: str, frame_data: bytes):
    """Broadcast frame to all viewers of a stream."""
    if user_id in stream_viewers:
        frame_b64 = base64.b64encode(frame_data).decode()
        dead_viewers = []
        
        for viewer in stream_viewers[user_id]:
            try:
                await viewer.send_text(frame_b64)
            except:
                dead_viewers.append(viewer)
        
        # Clean up dead connections
        for dead in dead_viewers:
            stream_viewers[user_id].remove(dead)

