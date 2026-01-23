"""
Antigravity Remote - API Routes
REST endpoints for the FastAPI application.
"""

import base64
import io
import os
from fastapi import APIRouter
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse

router = APIRouter()


# These will be injected by app.py
connected_clients = None
live_stream = None


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
        "version": "4.3.0",
        "clients": len(connected_clients) if connected_clients else 0,
        "features": ["live_stream", "two_way_chat", "scheduled_tasks", "undo_stack", "progress_bar"]
    }


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/stream/{user_id}")
async def stream_page(user_id: str):
    """HTML page for live streaming."""
    port = os.environ.get("PORT", 10000)
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Antigravity Live Stream</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ margin: 0; padding: 20px; background: #1a1a2e; color: white; font-family: system-ui; }}
            h1 {{ color: #00d4ff; margin: 0 0 20px 0; }}
            #stream {{ max-width: 100%; border: 2px solid #00d4ff; border-radius: 10px; }}
            .info {{ color: #888; margin-top: 10px; }}
            .status {{ color: #00ff88; }}
        </style>
    </head>
    <body>
        <h1>🔴 Antigravity Live</h1>
        <img id="stream" src="/stream/{user_id}/frame" alt="Loading...">
        <p class="info">Refreshing every 500ms | <span class="status" id="status">Connecting...</span></p>
        <script>
            const img = document.getElementById('stream');
            const status = document.getElementById('status');
            let errors = 0;
            setInterval(() => {{
                const newImg = new Image();
                newImg.onload = () => {{
                    img.src = newImg.src;
                    status.textContent = 'Connected';
                    errors = 0;
                }};
                newImg.onerror = () => {{
                    errors++;
                    status.textContent = errors > 3 ? 'Disconnected' : 'Buffering...';
                }};
                newImg.src = '/stream/{user_id}/frame?' + Date.now();
            }}, 500);
        </script>
    </body>
    </html>
    """)


@router.get("/stream/{user_id}/frame")
async def stream_frame(user_id: str):
    """Get latest frame for streaming."""
    if live_stream:
        frame = live_stream.get_frame(user_id)
        if frame:
            return StreamingResponse(io.BytesIO(frame), media_type="image/jpeg")
    return JSONResponse({"error": "No stream"}, status_code=404)
