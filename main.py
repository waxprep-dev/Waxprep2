"""
WaxPrep v2 — Main Application Entry Point
FastAPI server with Telegram + WhatsApp webhooks.

Webhook Architecture:
    /webhook/telegram (POST)
        ├── Degraded mode check → rejects if infrastructure is down
        ├── Secret token validation → required, fails closed
        ├── callback_query → handle_quiz_callback()  [button taps]
        └── message → process_telegram_message()      [text messages]
            └── Transient errors → 503 (Telegram retries)
            └── Permanent errors → 200 (no retry)
    
    /webhook/whatsapp (GET)  → Verification handshake
    /webhook/whatsapp (POST) → 501 Not Implemented (coming soon)

Cold Start Prevention:
    Use UptimeRobot (free) to ping /health every 5 minutes.
    This keeps Render free tier alive 24/7.
    Sign up at: https://uptimerobot.com
"""

import asyncio
import logging
import os
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
    - Validates Telegram token
    - Validates Groq API key (warns if missing)
    - Sets app.state.healthy based on all checks
    
    If BOTH Supabase AND Redis fail, the app will refuse to start.
    If only one fails, it enters degraded mode — /health reflects true status
    but the webhook will reject messages with 503 until recovery.
    
    Shutdown:
    - Cleanup connections
    - Log shutdown
    """
    logger.info("=" * 50)
    logger.info("WaxPrep v2 starting up...")
    startup_ok = True
    supabase_failed = False
    redis_failed = False

    # Test Supabase
    try:
        from database.client import supabase
        result = supabase.table("system_config").select("config_key").limit(1).execute()
        logger.info(f"✅ Supabase connected (rows: {len(result.data)})")
        app.state.supabase_ok = True
    except Exception as e:
        logger.critical(f"❌ Supabase connection FAILED: {e}")
        app.state.supabase_ok = False
        supabase_failed = True
        startup_ok = False

    # Test Redis
    try:
        from database.client import redis_client
        if redis_client.ping():
            logger.info("✅ Redis connected")
            app.state.redis_ok = True
        else:
            raise Exception("Redis ping returned False")
    except Exception as e:
        logger.critical(f"❌ Redis connection FAILED: {e}")
        app.state.redis_ok = False
        redis_failed = True
        startup_ok = False

    # If BOTH critical infrastructure failed, refuse to start
    if supabase_failed and redis_failed:
        logger.critical(
            "❌ Both Supabase AND Redis are unavailable. "
            "Application cannot function. Shutting down."
        )
        raise RuntimeError(
            "Critical infrastructure unavailable — Supabase and Redis both failed. "
            "Check credentials and network connectivity."
        )

    # Test Telegram bot token (syntax check, not actual API call)
    try:
        from config.settings import settings
        token = settings.TELEGRAM_BOT_TOKEN
        if token and len(token) > 20:
            logger.info(f"✅ Telegram token configured (length: {len(token)})")
            app.state.telegram_ok = True
        else:
            logger.warning("⚠️ Telegram token appears invalid (too short)")
            app.state.telegram_ok = False
    except Exception as e:
        logger.critical(f"❌ Telegram token check FAILED: {e}")
        app.state.telegram_ok = False
        startup_ok = False

    # Test Groq API key availability (warn but don't fail)
    try:
        groq_keys = settings.GROQ_API_KEYS
        if groq_keys and groq_keys[0]:
            logger.info(f"✅ Groq API keys configured ({len(groq_keys)} key(s))")
            app.state.groq_ok = True
        else:
            logger.warning("⚠️ No Groq API keys configured — AI responses will fail")
            app.state.groq_ok = False
    except Exception as e:
        logger.warning(f"⚠️ Groq key check failed: {e}")
        app.state.groq_ok = False

    # Check webhook secret in production
    if os.getenv("ENVIRONMENT", "development") == "production":
        webhook_secret = settings.TELEGRAM_WEBHOOK_SECRET
        if not webhook_secret:
            logger.critical(
                "❌ TELEGRAM_WEBHOOK_SECRET is not set in production! "
                "Webhook is UNPROTECTED. Set this immediately."
            )
        else:
            logger.info("✅ Telegram webhook secret configured")

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
    docs_url="/docs" if os.getenv("ENVIRONMENT", "development") != "production" else None,
)

# ── CORS (for future web dashboard) ──────────
# In production, restrict to the actual dashboard domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://waxprep.com",
        "https://app.waxprep.com",
    ] if os.getenv("ENVIRONMENT", "development") == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Include routers ──────────────────────────
from api.debug import router as debug_router
app.include_router(debug_router)


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

@app.api_route("/health", methods=["GET", "HEAD"])
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
    supabase_ok = getattr(app.state, "supabase_ok", False)
    redis_ok = getattr(app.state, "redis_ok", False)
    telegram_ok = getattr(app.state, "telegram_ok", False)
    groq_ok = getattr(app.state, "groq_ok", False)
    
    status_code = 200 if healthy else 503
    
    return JSONResponse(
        {
            "status": "ok" if healthy else "degraded",
            "version": "2.0.0",
            "uptime": getattr(app.state, "startup_time", "unknown"),
            "checks": {
                "supabase": "ok" if supabase_ok else "failed",
                "redis": "ok" if redis_ok else "failed",
                "telegram_token": "ok" if telegram_ok else "invalid",
                "groq_api": "ok" if groq_ok else "missing",
            }
        },
        status_code=status_code
    )


# ═══════════════════════════════════════════════
# TEST ENDPOINT (development only)
# ═══════════════════════════════════════════════

@app.get("/test-onboarding")
async def test_onboarding():
    """
    Run quick onboarding tests and return results directly.
    
    Only available in development mode.
    Useful for CI/CD and manual browser testing.
    """
    if os.getenv("ENVIRONMENT", "development") == "production":
        return JSONResponse(
            {"status": "error", "message": "Test endpoint disabled in production"},
            status_code=403
        )
    
    try:
        from tests.test_onboarding import run_quick_tests
    except ImportError as e:
        logger.error(f"Test module import failed: {e}")
        return JSONResponse(
            {"status": "error", "message": "Test module not available"},
            status_code=500
        )
    
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
    
    Security:
    - Secret token validation is REQUIRED. Fails closed if not configured.
    - Degraded mode check: rejects messages if infrastructure is down.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    # ── Check if app is healthy enough to process messages ──
    if not getattr(app.state, "healthy", True):
        logger.warning(
            f"[{request_id}] App is DEGRADED — rejecting message to allow recovery"
        )
        return JSONResponse(
            {"status": "degraded", "message": "Service temporarily unavailable"},
            status_code=503
        )

    # ── Validate secret token (anti-spoofing) — REQUIRED ──
    from config.settings import settings
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET
    
    if not expected_secret:
        # Secret is not configured. Fail closed — reject all requests.
        logger.critical(
            f"[{request_id}] TELEGRAM_WEBHOOK_SECRET is not configured! "
            f"Webhook is UNPROTECTED. Set this immediately."
        )
        return JSONResponse(
            {"status": "error", "message": "Server configuration error"},
            status_code=500
        )
    
    if secret_header != expected_secret:
        logger.warning(
            f"[{request_id}] Telegram webhook rejected: invalid secret token"
        )
        return JSONResponse({"status": "forbidden"}, status_code=403)

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
        error_str = str(e).lower()
        logger.error(
            f"[{request_id}] Message processing failed: {e}",
            exc_info=True
        )
        
        # Differentiate: transient errors → 503 (Telegram will retry)
        # Permanent errors → 200 (don't retry — it won't help)
        is_transient = any(phrase in error_str for phrase in [
            "timeout", "connection", "network", "temporary",
            "rate limit", "too many requests", "unavailable"
        ])
        
        if is_transient:
            return JSONResponse(
                {"status": "error", "request_id": request_id},
                status_code=503
            )
        else:
            return JSONResponse(
                {"status": "error", "request_id": request_id}
            )  # Default 200 — permanent error, don't retry


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

    logger.info(
        f"WhatsApp verification: mode={mode}, "
        f"token={'***' if token else 'None'}"
    )

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        return Response(content=str(challenge), media_type="text/plain")
    
    logger.warning(
        f"WhatsApp verification FAILED: mode={mode}, "
        f"token_match={token == settings.WHATSAPP_VERIFY_TOKEN}"
    )
    return JSONResponse({"status": "forbidden"}, status_code=403)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    WhatsApp message processing — NOT YET IMPLEMENTED.
    
    Returns 501 Not Implemented to prevent unauthorized use.
    This endpoint will be activated when WhatsApp integration is complete
    with proper authentication (X-Hub-Signature-256 validation).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    logger.warning(
        f"[{request_id}] WhatsApp webhook called but not implemented — "
        f"returning 501"
    )
    return JSONResponse(
        {
            "status": "not_implemented",
            "message": "WhatsApp integration coming soon"
        },
        status_code=501
    )


# ═══════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════

def _safe_get(dictionary: dict, *keys, default=None):
    """
    Safely traverse nested dictionaries without raising KeyError.
    
    Correctly handles None values — if a key exists but its value is None,
    traversal continues (unlike the old implementation which treated None
    the same as a missing key).
    
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
        if key not in dictionary:
            return default
        dictionary = dictionary[key]
    return dictionary


# ═══════════════════════════════════════════════
# RUNNER (for local development)
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    debug_mode = os.getenv("ENVIRONMENT", "development") != "production"
    
    logger.info(
        f"Starting WaxPrep in "
        f"{'development' if debug_mode else 'production'} mode"
    )
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        reload=debug_mode,
        log_level="debug" if debug_mode else "info",
    )
