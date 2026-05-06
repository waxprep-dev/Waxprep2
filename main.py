"""
WaxPrep v2 — Main Application Entry Point
FastAPI server with Telegram + WhatsApp webhooks.
"""

import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn


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
# TEST ENDPOINT — direct quick test (no timeout)
# ──────────────────────────────────────────────

@app.get("/test-onboarding")
async def test_onboarding():
    """Run quick onboarding tests and return results directly."""
    from tests.test_onboarding import run_quick_tests
    results = await run_quick_tests()
    passed = sum(1 for r in results if r["ok"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results
    }


# ──────────────────────────────────────────────
# TELEGRAM WEBHOOK
# ──────────────────────────────────────────────

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receives updates from Telegram and processes them."""
    import httpx
    from config.settings import settings
    
    try:
        body = await request.json()

        # Handle callback queries (quiz answer buttons)
        callback_query = body.get("callback_query", {})
        if callback_query:
            chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
            data = callback_query.get("data", "")  # "A", "B", "C", or "D"
            callback_id = callback_query.get("id")
            
            if chat_id and data:
                # Acknowledge the callback (remove loading state)
                url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(url, json={"callback_query_id": callback_id})
                
                # Process the answer as if the student typed it
                from telegram.handler import process_telegram_message
                await process_telegram_message(chat_id, data)
            
            return JSONResponse({"status": "ok"})

        # Handle regular text messages
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
