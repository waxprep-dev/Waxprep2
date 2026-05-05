"""
WaxPrep v2 — Main Application Entry Point
FastAPI server with Telegram + WhatsApp webhooks.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn
# (already has: from contextlib import asynccontextmanager, etc.)
# No new imports needed — the telegram import is inside the function


# ──────────────────────────────────────────────
# LIFESPAN — runs on startup and shutdown
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: test connections. Shutdown: cleanup."""
    print("WaxPrep v2 is starting up...")

    # Test Supabase
    try:
        from config.settings import settings
        from supabase import create_client
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        client.table('system_config').select('config_key').limit(1).execute()
        print("Supabase connection successful")
    except Exception as e:
        print(f"Supabase connection failed: {e}")

    # Test Redis
    try:
        from database.client import redis_client
        redis_client.ping()
        print("Redis connection successful")
    except Exception as e:
        print(f"Redis connection failed: {e}")

    print("WaxPrep v2 is ready!")
    yield
    print("WaxPrep v2 shutting down...")


# ──────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────

app = FastAPI(title="WaxPrep v2", lifespan=lifespan)


# ──────────────────────────────────────────────
# HEALTH CHECK
# ──────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}


# ──────────────────────────────────────────────
# TELEGRAM WEBHOOK
# ──────────────────────────────────────────────

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receives updates from Telegram and processes them."""
    try:
        body = await request.json()

        # Extract message text and chat ID
        message_data = body.get("message", {})
        chat = message_data.get("chat", {})
        chat_id = chat.get("id")
        text = message_data.get("text", "")

        if chat_id and text:
            from telegram.handler import process_telegram_message
            await process_telegram_message(chat_id, text)

        return JSONResponse({"status": "ok"})
    except Exception as e:
        print(f"Telegram webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=500)

# ──────────────────────────────────────────────
# WHATSAPP WEBHOOK
# ──────────────────────────────────────────────

@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """Verification endpoint for WhatsApp webhook setup."""
    from config.settings import settings
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return JSONResponse({"status": "error"}, status_code=403)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Receives messages from WhatsApp and processes them."""
    try:
        body = await request.json()
        # TODO: Process WhatsApp message
        print(f"WhatsApp message received")
        return JSONResponse({"status": "ok"})
    except Exception as e:
        print(f"WhatsApp webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=500)


# ──────────────────────────────────────────────
# RUNNER (for local development)
# ──────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
