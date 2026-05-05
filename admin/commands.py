"""
WaxPrep v2 — Admin Commands
Commands: DELETE ME, TEST ME, TEST ALL
"""

from database.client import supabase, redis_client
from telegram.sender import send_telegram_message

# Your Telegram chat ID for admin access
ADMIN_CHAT_IDS = {8568663974}


async def handle_admin_command(chat_id: int, text: str) -> bool:
    """Handle admin commands. Returns True if handled."""
    if chat_id not in ADMIN_CHAT_IDS:
        return False

    command = text.strip().upper()

    if command == "DELETE ME":
        await _delete_me(chat_id)
        return True
    if command == "TEST ME":
        await _run_quick_tests(chat_id)
        return True
    if command == "TEST ALL":
        await _run_all_tests(chat_id)
        return True

    return False


async def _delete_me(chat_id: int):
    """Hard-delete the current test account."""
    platform = "telegram"
    user_id = str(chat_id)

    try:
        session = (
            supabase.table("platform_sessions")
            .select("student_id")
            .eq("platform", platform)
            .eq("platform_user_id", user_id)
            .execute()
        )

        if session.data:
            student_id = session.data[0]["student_id"]
            supabase.table("platform_sessions").delete().eq("student_id", student_id).execute()
            supabase.table("students").delete().eq("id", student_id).execute()
            await send_telegram_message(chat_id, "✅ Account hard-deleted. Send *HI* to start fresh.")
        else:
            await send_telegram_message(chat_id, "No account found to delete.")
    except Exception as e:
        await send_telegram_message(chat_id, f"Delete failed: {e}")

    try:
        redis_client.delete(f"onboarding:{platform}:{user_id}")
    except Exception:
        pass


async def _run_quick_tests(chat_id: int):
    """Run 8 critical path tests and report results in Telegram."""
    await send_telegram_message(chat_id, "🧪 *Running quick tests...*")

    import telegram.sender as sender_module
    original_sender = sender_module.send_telegram_message

    from telegram.onboarding import handle_onboarding
    from database.onboarding_state import get_onboarding_state, clear_onboarding_state

    tests = [
        {
            "name": "SS Physics JAMB Lagos",
            "msgs": ["1","1","YES","David Emma","4","Physics","1","Lagos","5823","5823"],
            "must_have": ["danfo", "WAX-"]
        },
        {
            "name": "JSS2 Maths (skips exam)",
            "msgs": ["1","1","YES","Mary John","2","Maths","Lagos","3434","3434"],
            "must_have": ["biscuit", "WAX-"]
        },
        {
            "name": "Typo rnglish",
            "msgs": ["1","1","YES","Grace P","4","rnglish","1","Lagos","1113","1113"],
            "must_have": ["Achebe"]
        },
        {
            "name": "Number 1 defaults",
            "msgs": ["1","1","YES","Blessing O","3","1","Lagos","1117","1117"],
            "must_have": ["Mathematics"]
        },
        {
            "name": "I dont know defaults",
            "msgs": ["1","1","YES","Chioma N","3","i dont know","Lagos","1121","1121"],
            "must_have": ["Mathematics"]
        },
        {
            "name": "Short state Ka blocked",
            "msgs": ["1","1","YES","Ngozi E","4","English","1","Ka","Kaduna","1126","1126"],
            "must_have": ["Kaduna"]
        },
        {
            "name": "Weak PIN 1234 rejected",
            "msgs": ["1","1","YES","Joy Adamu","4","Physics","1","Lagos","1234","5824","5824"],
            "must_have": ["too easy"]
        },
        {
            "name": "Terms decline captured",
            "msgs": ["1","1","no","3"],
            "must_have": ["just looking"]
        },
    ]

    report = ""
    passed = 0
    failed = 0

    for i, test in enumerate(tests):
        # Fresh captured list for each test
        captured = []

        class TestMockSender:
            @staticmethod
            async def send_telegram_message(cid, text):
                captured.append(text)

        sender_module.send_telegram_message = TestMockSender.send_telegram_message

        cid = 70000 + i
        await clear_onboarding_state("telegram", str(cid))

        try:
            for msg in test["msgs"]:
                state = await get_onboarding_state("telegram", str(cid))
                await handle_onboarding(cid, state, msg)

            full_text = " ".join(captured)
            all_ok = all(c.lower() in full_text.lower() for c in test["must_have"])

            if all_ok:
                passed += 1
                report += f"  ✅ {test['name']}\n"
            else:
                failed += 1
                missing = [c for c in test["must_have"] if c.lower() not in full_text.lower()]
                report += f"  ❌ {test['name']} — missing: {', '.join(missing)}\n"
        except Exception as e:
            failed += 1
            report += f"  🔴 {test['name']} — crashed: {str(e)[:80]}\n"

    # Restore original sender BEFORE sending results
    sender_module.send_telegram_message = original_sender

    total = passed + failed
    summary = f"📊 *Results: {passed}/{total} passed*"

    if failed == 0:
        summary += "\n\n🎉 All tests passed!"
    else:
        summary += f"\n\n🔴 {failed} test(s) failed."

    await send_telegram_message(chat_id, summary + "\n\n" + report)


async def _run_all_tests(chat_id: int):
    """Run expanded test suite (20+ scenarios)."""
    await send_telegram_message(chat_id, "🧪 *Running full test suite... this may take a minute.*")

    import telegram.sender as sender_module
    original_sender = sender_module.send_telegram_message

    from telegram.onboarding import handle_onboarding
    from database.onboarding_state import get_onboarding_state, clear_onboarding_state

    tests = [
        # Happy paths (8)
        {"name": "SS Physics JAMB", "msgs": ["1","1","YES","A One","4","Physics","1","Lagos","1001","1001"], "must_have": ["danfo","WAX-"]},
        {"name": "SS Chemistry WAEC", "msgs": ["1","2","YES","B Two","5","Chemistry","2","Abuja","1002","1002"], "must_have": ["puff-puff","WAX-"]},
        {"name": "SS Biology NECO", "msgs": ["1","1","YES","C Three","4","Biology","3","Rivers","1003","1003"], "must_have": ["egusi","WAX-"]},
        {"name": "SS Economics JAMB", "msgs": ["1","3","YES","D Four","5","Economics","1","Kano","1004","1004"], "must_have": ["tomato","WAX-"]},
        {"name": "JSS2 Maths", "msgs": ["1","1","YES","E Five","2","Maths","Lagos","1005","1005"], "must_have": ["biscuit","WAX-"]},
        {"name": "JSS1 Science", "msgs": ["1","1","YES","F Six","1","science","Kano","1006","1006"], "must_have": ["spoon","Basic Science"]},
        {"name": "SS Government", "msgs": ["1","2","YES","G Seven","5","Government","2","Oyo","1007","1007"], "must_have": ["INEC","WAX-"]},
        {"name": "SS Literature", "msgs": ["1","1","YES","H Eight","4","Literature","1","Enugu","1008","1008"], "must_have": ["Achebe","WAX-"]},

        # Typos (5)
        {"name": "Typo physcs", "msgs": ["1","1","YES","I1","4","physcs","1","Lagos","2001","2001"], "must_have": ["danfo"]},
        {"name": "Typo chemstry", "msgs": ["1","1","YES","I2","5","chemstry","2","Lagos","2002","2002"], "must_have": ["puff-puff"]},
        {"name": "Typo biolgy", "msgs": ["1","1","YES","I3","4","biolgy","1","Lagos","2003","2003"], "must_have": ["egusi"]},
        {"name": "Typo goverment", "msgs": ["1","1","YES","I4","5","goverment","2","Lagos","2004","2004"], "must_have": ["INEC"]},
        {"name": "Typo econmics", "msgs": ["1","1","YES","I5","5","econmics","2","Lagos","2005","2005"], "must_have": ["tomato"]},

        # Number confusion (3)
        {"name": "Number 1 subj", "msgs": ["1","1","YES","J1","3","1","Lagos","3001","3001"], "must_have": ["Mathematics"]},
        {"name": "Number 2 subj", "msgs": ["1","1","YES","J2","5","2","Lagos","3002","3002"], "must_have": ["Mathematics"]},
        {"name": "Number 3 subj", "msgs": ["1","1","YES","J3","4","3","Lagos","3003","3003"], "must_have": ["Mathematics"]},

        # Edge cases (4)
        {"name": "I dont know", "msgs": ["1","1","YES","K1","3","i dont know","Lagos","4001","4001"], "must_have": ["No wahala","Mathematics"]},
        {"name": "Short state Ka", "msgs": ["1","1","YES","K2","4","English","1","Ka","Kaduna","4002","4002"], "must_have": ["doesn't look like"]},
        {"name": "Weak PIN", "msgs": ["1","1","YES","K3","4","Physics","1","Lagos","1234","4003","4003"], "must_have": ["too easy"]},
        {"name": "Decline terms", "msgs": ["1","1","no","3"], "must_have": ["No problem","just looking"]},
    ]

    report = ""
    passed = 0
    failed = 0
    failures = []

    for i, test in enumerate(tests):
        # Fresh captured list for each test
        captured = []

        class TestMockSender:
            @staticmethod
            async def send_telegram_message(cid, text):
                captured.append(text)

        sender_module.send_telegram_message = TestMockSender.send_telegram_message

        cid = 80000 + i
        await clear_onboarding_state("telegram", str(cid))

        try:
            for msg in test["msgs"]:
                state = await get_onboarding_state("telegram", str(cid))
                await handle_onboarding(cid, state, msg)

            full_text = " ".join(captured)
            all_ok = all(c.lower() in full_text.lower() for c in test["must_have"])

            if all_ok:
                passed += 1
            else:
                failed += 1
                missing = [c for c in test["must_have"] if c.lower() not in full_text.lower()]
                failures.append(f"  ❌ {test['name']}: missing {missing}")
        except Exception as e:
            failed += 1
            failures.append(f"  🔴 {test['name']}: crashed - {str(e)[:80]}")

    # Restore original sender BEFORE sending results
    sender_module.send_telegram_message = original_sender

    total = passed + failed
    summary = f"📊 *Full Results: {passed}/{total} passed*"

    if failed == 0:
        summary += "\n\n🎉 All 20 tests passed!"
    else:
        summary += f"\n\n🔴 {failed} failed:"
        for f in failures[:10]:
            summary += f"\n{f}"

    await send_telegram_message(chat_id, summary)
