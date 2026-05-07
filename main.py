"""
WaxPrep v2 — Main Application Entry Point
FastAPI server with Telegram + WhatsApp webhooks.

Webhook Architecture:
    /webhook/telegram (POST)
        ├── callback_query → handle_quiz_callback()  [button taps]
        └── message → process_telegram_message()      [text messages]
    
    /webhook/whatsapp (GET)  → Verification handshake
    /webhook/whatsapp (POST) → Message processing

Cold Start Prevention:
    Use UptimeRobot (free) to ping /health every 5 minutes.
    This keeps Render free tier alive 24/7.
    Sign up at: https://uptimerobot.com
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# ── Logger ────────────────────────────────────
logger = logging.getLogger("waxprep.main")

# ═══════════════════════════════════════════════
# LIFESPAN — runs on startup and shutdown
# ═══════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Startup:
    - Validates Supabase connection
    - Validates Redis connection
    - Logs readiness state
    
    Shutdown:
    - Cleanup connections
    - Log shutdown
    
    Note: Startup failures are logged but don't prevent app start.
    The app enters "degraded mode" — /health reflects true status.
    """
    logger.info("=" * 50)
    logger.info("WaxPrep v2 starting up...")
    startup_ok = True

    # Test Supabase
    try:
        from database.client import supabase
        result = supabase.table("system_config").select("config_key").limit(1).execute()
        logger.info(f"✅ Supabase connected (rows: {len(result.data)})")
    except Exception as e:
        logger.critical(f"❌ Supabase connection FAILED: {e}")
        app.state.supabase_ok = False
        startup_ok = False

    # Test Redis
    try:
        from database.client import redis_client
        if redis_client.ping():
            logger.info("✅ Redis connected")
        else:
            raise Exception("Redis ping returned False")
    except Exception as e:
        logger.critical(f"❌ Redis connection FAILED: {e}")
        app.state.redis_ok = False
        startup_ok = False

    # Test Telegram bot token (syntax check, not actual API call)
    try:
        from config.settings import settings
        token = settings.TELEGRAM_BOT_TOKEN
        if token and len(token) > 20:
            logger.info(f"✅ Telegram token configured (length: {len(token)})")
        else:
            logger.warning("⚠️ Telegram token appears invalid (too short)")
    except Exception as e:
        logger.critical(f"❌ Telegram token check FAILED: {e}")
        startup_ok = False

    # Store overall health
    app.state.healthy = startup_ok
    app.state.startup_time = datetime.now(timezone.utc).isoformat()

    if startup_ok:
        logger.info("✅ WaxPrep v2 is READY")
    else:
        logger.warning("⚠️ WaxPrep v2 started in DEGRADED mode — check /health")
    
    logger.info("=" * 50)

    yield  # ── Application runs here ──

    logger.info("WaxPrep v2 shutting down...")


# ═══════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════

app = FastAPI(
    title="WaxPrep v2",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if __import__("os").getenv("ENV") != "production" else None,
)

# ── CORS (for future web dashboard) ──────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════
# MIDDLEWARE — Request ID & Logging
# ═══════════════════════════════════════════════

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """
    Add a unique request ID and log every request.
    
    The request_id is stored in request.state for downstream handlers.
    """
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    
    start_time = datetime.now(timezone.utc)
    
    try:
        response = await call_next(request)
        elapsed_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"→ {response.status_code} ({elapsed_ms:.0f}ms)"
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        logger.error(f"[{request_id}] Unhandled error: {e}", exc_info=True)
        return JSONResponse(
            {"status": "error", "request_id": request_id},
            status_code=500
        )


# ═══════════════════════════════════════════════
# HEALTH CHECK — enhanced
# ═══════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Used by:
    - UptimeRobot (prevent Render cold starts)
    - Load balancers
    - Monitoring dashboards
    
    Returns true health status, not just "ok".
    """
    healthy = getattr(app.state, "healthy", False)
    supabase_ok = getattr(app.state, "supabase_ok", True)
    redis_ok = getattr(app.state, "redis_ok", True)
    
    status_code = 200 if healthy else 503
    
    return JSONResponse(
        {
            "status": "ok" if healthy else "degraded",
            "version": "2.0.0",
            "uptime": getattr(app.state, "startup_time", "unknown"),
            "checks": {
                "supabase": "ok" if supabase_ok else "failed",
                "redis": "ok" if redis_ok else "failed",
            }
        },
        status_code=status_code
    )


# ═══════════════════════════════════════════════
# TEST ENDPOINT
# ═══════════════════════════════════════════════

@app.get("/test-onboarding")
async def test_onboarding():
    """
    Run quick onboarding tests and return results directly.
    
    No timeout, no WebSocket — plain JSON response.
    Useful for CI/CD and manual browser testing.
    """
    from tests.test_onboarding import run_quick_tests
    
    logger.info("Running onboarding tests...")
    results = await run_quick_tests()
    
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    
    logger.info(f"Test results: {passed}/{total} passed")
    
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{(passed/total*100):.0f}%" if total > 0 else "N/A",
        "results": results
    }


# ═══════════════════════════════════════════════
# TELEGRAM WEBHOOK
# ═══════════════════════════════════════════════

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Receives updates from Telegram and routes them appropriately.
    
    Two types of updates:
    1. callback_query — User tapped an inline keyboard button (quiz answer)
       → Routed to handle_quiz_callback()
    
    2. message — User sent a text message
       → Routed to process_telegram_message()
    
    Security: Validates Telegram secret token header (if configured).
    """
    request_id = getattr(request.state, "request_id", "unknown")

    # ── Validate secret token (anti-spoofing) ──
    try:
        from config.settings import settings
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        expected_secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None)
        
        if expected_secret and secret_header != expected_secret:
            logger.warning(
                f"[{request_id}] Telegram webhook rejected: invalid secret token"
            )
            return JSONResponse({"status": "forbidden"}, status_code=403)
    except Exception as e:
        logger.error(f"[{request_id}] Secret validation error: {e}")
        # Don't block on config errors — log and continue

    # ── Parse request body ──
    try:
        body = await request.json()
        logger.debug(f"[{request_id}] Telegram update: {str(body)[:200]}")
    except Exception as e:
        logger.error(f"[{request_id}] Failed to parse JSON body: {e}")
        return JSONResponse({"status": "invalid_json"}, status_code=400)

    # ── Handle callback queries (quiz answer buttons) ──
    callback_query = body.get("callback_query")
    if callback_query:
        chat_id = _safe_get(callback_query, "message", "chat", "id")
        data = callback_query.get("data", "")  # "A", "B", "C", or "D"
        callback_id = callback_query.get("id")

        if not all([chat_id, data, callback_id]):
            logger.warning(
                f"[{request_id}] Incomplete callback_query: "
                f"chat_id={chat_id}, data={data}, callback_id={callback_id}"
            )
            return JSONResponse({"status": "bad_request"}, status_code=400)

        logger.info(
            f"[{request_id}] Callback query: chat_id={chat_id}, "
            f"answer={data}"
        )

        try:
            from telegram.handler import handle_quiz_callback
            await handle_quiz_callback(chat_id, callback_id, data)
            logger.info(f"[{request_id}] Callback processed successfully")
        except Exception as e:
            logger.error(
                f"[{request_id}] Callback processing failed: {e}",
                exc_info=True
            )
            # Still return 200 — Telegram already got acknowledgment
            # from answer_callback_query() inside handle_quiz_callback()

        return JSONResponse({"status": "ok"})

    # ── Handle text messages ──
    message_data = body.get("message")
    if not message_data:
        logger.debug(f"[{request_id}] Update has no message or callback_query")
        return JSONResponse({"status": "ok"})  # ACK non-message updates

    chat = message_data.get("chat", {})
    chat_id = chat.get("id")
    text = message_data.get("text", "")

    if not chat_id or not text:
        logger.debug(f"[{request_id}] Message missing chat_id or text")
        return JSONResponse({"status": "ok"})

    logger.info(
        f"[{request_id}] Text message: chat_id={chat_id}, "
        f"text={text[:100]}..."
    )

    try:
        from telegram.handler import process_telegram_message
        await process_telegram_message(chat_id, text)
        logger.info(f"[{request_id}] Message processed successfully")
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.error(
            f"[{request_id}] Message processing failed: {e}",
            exc_info=True
        )
        # Return 200 anyway — prevents Telegram retry spam
        # The error is logged for debugging
        return JSONResponse({"status": "error", "request_id": request_id})


# ═══════════════════════════════════════════════
# WHATSAPP WEBHOOK
# ═══════════════════════════════════════════════

@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """
    Verification endpoint for WhatsApp webhook setup.
    
    Meta sends a GET request with:
    - hub.mode (should be "subscribe")
    - hub.verify_token (must match your configured token)
    - hub.challenge (return this value as plain text to verify)
    
    Returns:
        200 with challenge string if verified
        403 if token mismatch
    """
    from config.settings import settings
    
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    logger.info(f"WhatsApp verification: mode={mode}, token={'***' if token else 'None'}")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        return Response(content=str(challenge), media_type="text/plain")
    
    logger.warning(f"WhatsApp verification FAILED: mode={mode}, token_match={token == settings.WHATSAPP_VERIFY_TOKEN}")
    return JSONResponse({"status": "forbidden"}, status_code=403)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Receives messages from WhatsApp and processes them.
    
    TODO: Implement WhatsApp message processing.
    For now, returns 200 to acknowledge receipt.
    
    Future: Route to same handler as Telegram (multi-platform support).
    """
    request_id = getattr(request.state, "request_id", "unknown")

    try:
        body = await request.json()
        logger.info(f"[{request_id}] WhatsApp message received: {str(body)[:200]}")
        
        # TODO: Extract phone number and message text
        # TODO: Lookup or create student by WhatsApp phone number
        # TODO: Route to process_telegram_message() or equivalent
        
        return JSONResponse({
            "status": "ok",
            "message": "WhatsApp integration coming soon"
        })
    except Exception as e:
        logger.error(f"[{request_id}] WhatsApp webhook error: {e}", exc_info=True)
        return JSONResponse({"status": "error"}, status_code=500)


# ═══════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════

def _safe_get(dictionary: dict, *keys, default=None):
    """
    Safely traverse nested dictionaries without raising KeyError.
    
    Example:
        _safe_get(body, "callback_query", "message", "chat", "id")
        → body["callback_query"]["message"]["chat"]["id"] or None
    
    Args:
        dictionary: The dict to traverse
        *keys: Sequence of keys to follow
        default: Value to return if any key is missing
        
    Returns:
        The value at the nested path, or default
    """
    for key in keys:
        if not isinstance(dictionary, dict):
            return default
        dictionary = dictionary.get(key, default)
        if dictionary is default:
            return default
    return dictionary


# ═══════════════════════════════════════════════
# RUNNER (for local development)
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    import os
    debug_mode = os.getenv("ENV", "development") != "production"
    
    logger.info(f"Starting WaxPrep in {'development' if debug_mode else 'production'} mode")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        reload=debug_mode,
        log_level="info" if not debug_mode else "debug",
    )
