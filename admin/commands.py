"""
WaxPrep v2 — Admin Commands
Commands: DELETE ME, TEST ME, TEST ALL, TEST AI
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
    if command == "TEST AI":
        await _run_ai_behavior_tests(chat_id)
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
        {"name": "SS Physics JAMB Lagos", "msgs": ["1","1","YES","David Emma","4","Physics","1","Lagos","5823","5823"], "must_have": ["danfo", "WAX-"]},
        {"name": "JSS2 Maths (skips exam)", "msgs": ["1","1","YES","Mary John","2","Maths","Lagos","3434","3434"], "must_have": ["biscuit", "WAX-"]},
        {"name": "Typo rnglish", "msgs": ["1","1","YES","Grace P","4","rnglish","1","Lagos","1113","1113"], "must_have": ["Achebe"]},
        {"name": "Number 1 defaults", "msgs": ["1","1","YES","Blessing O","3","1","Lagos","1117","1117"], "must_have": ["Mathematics"]},
        {"name": "I dont know defaults", "msgs": ["1","1","YES","Chioma N","3","i dont know","Lagos","1121","1121"], "must_have": ["Mathematics"]},
        {"name": "Short state Ka blocked", "msgs": ["1","1","YES","Ngozi E","4","English","1","Ka","Kaduna","1126","1126"], "must_have": ["Kaduna"]},
        {"name": "Weak PIN 1234 rejected", "msgs": ["1","1","YES","Joy Adamu","4","Physics","1","Lagos","1234","5824","5824"], "must_have": ["too easy"]},
        {"name": "Terms decline captured", "msgs": ["1","1","no","3"], "must_have": ["just looking"]},
    ]

    report = ""
    passed = 0
    failed = 0

    for i, test in enumerate(tests):
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
    # Cooldown check
    cooldown_key = "test_all_cooldown"
    if redis_client.get(cooldown_key):
        await send_telegram_message(chat_id, "⏳ Tests already running. Please wait.")
        return
    redis_client.setex(cooldown_key, 300, "1")  # 5 minute cooldown

    await send_telegram_message(chat_id, "🧪 *Running full test suite... this may take a minute.*")

    import telegram.sender as sender_module
    original_sender = sender_module.send_telegram_message
    from telegram.onboarding import handle_onboarding
    from database.onboarding_state import get_onboarding_state, clear_onboarding_state

    tests = [
        {"name": "SS Physics JAMB", "msgs": ["1","1","YES","A One","4","Physics","1","Lagos","1001","1001"], "must_have": ["danfo","WAX-"]},
        {"name": "SS Chemistry WAEC", "msgs": ["1","2","YES","B Two","5","Chemistry","2","Abuja","1002","1002"], "must_have": ["puff-puff","WAX-"]},
        {"name": "SS Biology NECO", "msgs": ["1","1","YES","C Three","4","Biology","3","Rivers","1003","1003"], "must_have": ["egusi","WAX-"]},
        {"name": "SS Economics JAMB", "msgs": ["1","3","YES","D Four","5","Economics","1","Kano","1004","1004"], "must_have": ["tomato","WAX-"]},
        {"name": "JSS2 Maths", "msgs": ["1","1","YES","E Five","2","Maths","Lagos","1005","1005"], "must_have": ["biscuit","WAX-"]},
        {"name": "JSS1 Science", "msgs": ["1","1","YES","F Six","1","science","Kano","1006","1006"], "must_have": ["spoon","Basic Science"]},
        {"name": "SS Government", "msgs": ["1","2","YES","G Seven","5","Government","2","Oyo","1007","1007"], "must_have": ["INEC","WAX-"]},
        {"name": "SS Literature", "msgs": ["1","1","YES","H Eight","4","Literature","1","Enugu","1008","1008"], "must_have": ["Achebe","WAX-"]},
        {"name": "Typo physcs", "msgs": ["1","1","YES","I1","4","physcs","1","Lagos","2001","2001"], "must_have": ["danfo"]},
        {"name": "Typo chemstry", "msgs": ["1","1","YES","I2","5","chemstry","2","Lagos","2002","2002"], "must_have": ["puff-puff"]},
        {"name": "Typo biolgy", "msgs": ["1","1","YES","I3","4","biolgy","1","Lagos","2003","2003"], "must_have": ["egusi"]},
        {"name": "Typo goverment", "msgs": ["1","1","YES","I4","5","goverment","2","Lagos","2004","2004"], "must_have": ["INEC"]},
        {"name": "Typo econmics", "msgs": ["1","1","YES","I5","5","econmics","2","Lagos","2005","2005"], "must_have": ["tomato"]},
        {"name": "Number 1 subj", "msgs": ["1","1","YES","J1","3","1","Lagos","3001","3001"], "must_have": ["Mathematics"]},
        {"name": "Number 2 subj", "msgs": ["1","1","YES","J2","5","2","Lagos","3002","3002"], "must_have": ["Mathematics"]},
        {"name": "Number 3 subj", "msgs": ["1","1","YES","J3","4","3","Lagos","3003","3003"], "must_have": ["Mathematics"]},
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


# ═══════════════════════════════════════════════
# AI BEHAVIOR TEST — ALL INLINE
# ═══════════════════════════════════════════════

STUDENT_TYPES = {
    "confused": {
        "name": "Confused Student",
        "messages": [
            "Explain osmosis to me",
            "I don't understand",
            "Still confused",
            "Can you make it simpler?",
            "I still don't get it",
            "What does that mean?",
        ],
    },
    "fast_learner": {
        "name": "Fast Learner",
        "messages": [
            "Teach me quadratic equations",
            "I get it. What's next?",
            "That was easy. Give me something harder.",
            "Next topic?",
            "I already know this. Move on.",
        ],
    },
    "exam_anxious": {
        "name": "Exam Anxious",
        "messages": [
            "JAMB is in 2 weeks and I don't know anything",
            "I'm going to fail",
            "What should I focus on?",
            "Is it too late?",
        ],
    },
    "random_spammer": {
        "name": "Random Spammer",
        "messages": [
            "hi",
            "explain physics",
            "no wait chemistry",
            "you pick",
            "lol",
            "what's your name",
            "give me a test",
        ],
    },
    "silent": {
        "name": "Silent Student",
        "messages": [
            "teach me biology",
            "ok",
            "k",
            "yes",
            "go on",
        ],
    },
    "corrector": {
        "name": "Corrective Student",
        "messages": [
            "Explain the periodic table",
            "That's not right",
            "Actually, oxygen is O not O2",
            "Check your facts",
        ],
    },
}


def _analyze_responses(messages: list, responses: list, student_type: str) -> dict:
    """Analyze AI responses for failures."""
    failures = []
    passes = []
    warnings = []
    
    full = " ".join(responses).lower()
    student_text = " ".join(messages).lower()
    
    if "don't worry" in full or "dont worry" in full:
        failures.append("Used 'don't worry' (dismissive)")
    
    if "wrong." in full or "incorrect." in full:
        failures.append("Used 'wrong' or 'incorrect'")
    
    for r in responses:
        if r.count("?") > 1:
            failures.append("Asked multiple questions in one message")
            break
    
    for r in responses:
        if len(r) > 400:
            warnings.append("Some responses were long (>400 chars)")
            break
    
    nigerian_terms = ["danfo", "suya", "puff-puff", "egusi", "okada", "keke", "nepa", "wahala", "jollof", "garri"]
    if any(term in full for term in nigerian_terms):
        passes.append("Used Nigerian examples")
    else:
        warnings.append("No Nigerian examples detected")
    
    if student_type == "confused":
        confusion_signals = ["step back", "simpler", "another way", "different example", "no wahala", "let's try", "break it down"]
        if any(signal in full for signal in confusion_signals):
            passes.append("Responded to confusion with simplification")
        else:
            failures.append("Did not respond to repeated confusion signals")
    
    if student_type == "fast_learner":
        progression_signals = ["harder", "next level", "more difficult", "advanced", "next topic"]
        if any(signal in full for signal in progression_signals):
            passes.append("Offered progression for fast learner")
        else:
            warnings.append("Did not clearly offer progression")
    
    if student_type == "exam_anxious":
        if "don't worry" not in full:
            passes.append("Avoided 'don't worry' for anxious student")
        action_signals = ["let's", "plan", "focus", "today", "start"]
        if any(signal in full for signal in action_signals):
            passes.append("Offered concrete action plan")
    
    total = len(failures) + len(passes) + len(warnings)
    if total == 0:
        score = 50
    else:
        score = int((len(passes) / total) * 100)
    
    return {
        "failures": failures,
        "passes": passes,
        "warnings": warnings,
        "score": score,
        "verdict": "PASS" if len(failures) == 0 else "FAIL",
    }


async def _run_ai_behavior_tests(chat_id: int):
    """Run AI behavior tests — ALL INLINE, NO EXTERNAL FILES NEEDED."""
    # Cooldown check — prevent multiple simultaneous runs
    cooldown_key = "test_ai_cooldown"
    if redis_client.get(cooldown_key):
        await send_telegram_message(chat_id, "⏳ Test AI already ran recently. Wait 5 minutes before running again.")
        return
    redis_client.setex(cooldown_key, 300, "1")  # 5 minute cooldown

    await send_telegram_message(chat_id, "🧠 *Running AI behavior tests...*\nSimulating student types. This will take ~1 minute.")

    import telegram.sender as sender_module
    original_sender = sender_module.send_telegram_message

    from ai.brain import think

    test_student = {
        "id": "test-001",
        "name": "Test Student",
        "class_level": "SS3",
        "target_exam": "JAMB",
        "subjects": ["Mathematics", "English", "Physics", "Chemistry"],
        "state": "Lagos",
        "language_preference": "english",
        "current_streak": 5,
    }

    topics = ["osmosis", "quadratic equations", "periodic table", "supply and demand"]
    student_type_keys = list(STUDENT_TYPES.keys())
    
    report_lines = []
    total_passed = 0
    total_failed = 0

    for i, stype in enumerate(student_type_keys):
        profile = STUDENT_TYPES[stype]
        topic = topics[i % len(topics)]
        
        messages = list(profile["messages"])
        if "{topic}" in messages[0] or "Explain" in messages[0] or "Teach" in messages[0] or "teach" in messages[0]:
            messages[0] = messages[0].replace("{topic}", topic)
            if "Explain" not in messages[0] and "Teach" not in messages[0] and "teach" not in messages[0] and "JAMB" not in messages[0] and "hi" not in messages[0].lower():
                messages.insert(0, f"Teach me about {topic}")

        conversation_history = []
        responses = []

        for msg in messages:
            try:
                response = await think(
                    message=msg,
                    student=test_student,
                    conversation_history=conversation_history,
                    recent_subject=topic,
                    context_str="",
                    is_practice=False,
                )
            except Exception as e:
                response = f"[ERROR: {e}]"

            conversation_history.append({"role": "user", "content": msg})
            conversation_history.append({"role": "assistant", "content": response})
            responses.append(response)

        analysis = _analyze_responses(messages, responses, stype)

        if analysis["verdict"] == "PASS":
            total_passed += 1
            emoji = "✅"
        else:
            total_failed += 1
            emoji = "❌"

        report_lines.append(f"{emoji} *{profile['name']}* — Score: {analysis['score']}/100")
        for f in analysis.get("failures", []):
            report_lines.append(f"   🔴 {f}")
        for w in analysis.get("warnings", [])[:2]:
            report_lines.append(f"   🟡 {w}")
        for p in analysis.get("passes", []):
            report_lines.append(f"   🟢 {p}")

    sender_module.send_telegram_message = original_sender

    total = total_passed + total_failed
    summary = f"📊 *AI Behavior Results: {total_passed}/{total} passed*"
    if total_failed == 0:
        summary += "\n\n🎉 All student types passed!"

    full_report = summary + "\n\n" + "\n".join(report_lines)
    
    if len(full_report) > 4000:
        await send_telegram_message(chat_id, full_report[:4000])
        await send_telegram_message(chat_id, full_report[4000:])
    else:
        await send_telegram_message(chat_id, full_report)
