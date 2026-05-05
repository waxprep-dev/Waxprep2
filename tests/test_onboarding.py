@app.get("/test-onboarding")
async def test_onboarding():
    """Quick test to confirm endpoint works."""
    return {"status": "ok", "message": "Test endpoint is working", "count": 1}
