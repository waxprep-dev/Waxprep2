"""Simple onboarding tests."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock the sender
import telegram.sender as sender_module

captured = []

class MockSender:
    @staticmethod
    async def send_telegram_message(chat_id, text):
        captured.append(text)

sender_module.send_telegram_message = MockSender.send_telegram_message

from telegram.onboarding import handle_onboarding
from database.onboarding_state import get_onboarding_state, clear_onboarding_state


async def run_quick_tests():
    """Run 5 simple scenarios and return results."""
    global captured
    
    tests = [
        {
            "name": "SS student Physics",
            "messages": ["1", "1", "YES", "David Emma", "4", "Physics", "1", "Lagos", "5823", "5823"],
        },
        {
            "name": "JSS student Maths", 
            "messages": ["1", "1", "YES", "Mary John", "2", "Maths", "Lagos", "3434", "3434"],
        },
        {
            "name": "Typo rnglish",
            "messages": ["1", "1", "YES", "Grace P", "4", "rnglish", "1", "Lagos", "1113", "1113"],
        },
        {
            "name": "Number as subject",
            "messages": ["1", "1", "YES", "Blessing O", "3", "1", "Lagos", "1117", "1117"],
        },
        {
            "name": "Decline terms",
            "messages": ["1", "1", "no", "3"],
        },
    ]
    
    results = []
    
    for i, test in enumerate(tests):
        captured.clear()
        chat_id = 50000 + i
        await clear_onboarding_state("telegram", str(chat_id))
        
        for msg in test["messages"]:
            state = await get_onboarding_state("telegram", str(chat_id))
            await handle_onboarding(chat_id, state, msg)
        
        full = " ".join(captured)
        ok = True
        issues = []
        
        if "1 together" in full.lower(): 
            ok = False
            issues.append("Number stored as subject")
        if "rnglish" in full.lower() and "English" not in full:
            ok = False
            issues.append("Typo not corrected")
        if "Ka!" in full:
            ok = False
            issues.append("Short state not rejected")
            
        results.append({
            "name": test["name"],
            "ok": ok,
            "issues": issues,
            "responses": len(captured)
        })
    
    return results
