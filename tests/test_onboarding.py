"""
WaxPrep v2 — Automated Onboarding Test Harness
Runs 50+ scenarios through the onboarding flow.
Access via /test-onboarding in production.
"""

import asyncio
import json
import sys
import os
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Mock Telegram sender ──────────────────────
captured_messages = []

class MockSender:
    @staticmethod
    async def send_telegram_message(chat_id, text):
        captured_messages.append({
            "chat_id": chat_id,
            "text": text,
            "timestamp": datetime.utcnow().isoformat()
        })

import telegram.sender as sender_module
sender_module.send_telegram_message = MockSender.send_telegram_message

from telegram.onboarding import handle_onboarding
from database.onboarding_state import get_onboarding_state, clear_onboarding_state, save_onboarding_state
from content.subject_hooks import normalize_subject, get_magic_trick

# ── Problem Detector ──────────────────────────
def scan_for_problems(responses: list, scenario_desc: str) -> list:
    problems = []
    full_text = " ".join([r["text"] for r in responses])
    lower_text = full_text.lower()

    # Critical bugs
    if "we'll tackle 1 together" in lower_text:
        problems.append("🔴 STORED '1' AS SUBJECT NAME")
    if "we'll tackle rnglish" in lower_text:
        problems.append("🔴 TYPO 'RNGLISH' STORED AS SUBJECT")
    if "jamb" in lower_text and "jss" in lower_text:
        problems.append("🔴 JSS STUDENT ASKED ABOUT EXAM")
    if any(f"we'll tackle {d}" in lower_text for d in ["1","2","3","4","5","6","7","8","9","0"]):
        problems.append("🔴 NUMBER STORED AS SUBJECT")

    # Medium issues
    if "ka!" in lower_text and "kano" not in lower_text:
        problems.append("🟡 SHORT STATE 'KA' ACCEPTED")

    # Magic Trick checks
    magic_subjects = ["physics","maths","mathematics","english","chemistry","biology","economics","government","literature","commerce","accounting","basic science","basic mathematics"]
    if "i don't have a special trick" in lower_text:
        mentioned = [s for s in magic_subjects if s in lower_text]
        if not mentioned:
            problems.append("🟡 MAGIC TRICK BYPASSED — NO SUBJECT MATCHED")

    # Acknowledgment check
    ack_phrases = ["got it", "nice one", "good", "alright", "okay", "noted"]
    ack_count = sum(1 for p in ack_phrases if p in lower_text)
    if ack_count == 0 and len(responses) > 4:
        problems.append("🟡 NO ACKNOWLEDGMENT PHRASES")

    # WAX ID check
    if "wax-" not in lower_text and len(responses) > 6:
        problems.append("🟡 NO WAX ID IN FINAL WELCOME")

    return problems


# ── Scenario Runner ───────────────────────────
class ScenarioRunner:
    def __init__(self, chat_id: int, messages: list):
        self.chat_id = chat_id
        self.messages = messages

    async def run(self):
        global captured_messages
        start_idx = len(captured_messages)
        await clear_onboarding_state("telegram", str(self.chat_id))

        for msg in self.messages:
            state = await get_onboarding_state("telegram", str(self.chat_id))
            await handle_onboarding(self.chat_id, state, msg)

        return captured_messages[start_idx:]


# ── ALL SCENARIOS ─────────────────────────────
SCENARIOS = [
    # HAPPY PATHS
    {"desc": "SS student — Physics, JAMB, Lagos", "msgs": ["1","1","YES","David Emmanuel","4","Physics","1","Lagos","5823","5823"]},
    {"desc": "SS student — WAEC, Chemistry, Abuja", "msgs": ["1","2","YES","Emeka Obi","5","Chemistry","2","Abuja","7294","7294"]},
    {"desc": "SS student — NECO, Biology, Rivers", "msgs": ["1","1","YES","Ada Nneka","4","Biology","3","Rivers","5551","5551"]},
    {"desc": "SS student — Economics, JAMB, Kano", "msgs": ["1","3","YES","Ibrahim Musa","5","Economics","1","Kano","5552","5552"]},
    {"desc": "SS student — Government, WAEC, Oyo", "msgs": ["1","2","YES","Musa Bello","5","Government","2","Oyo","5553","5553"]},
    {"desc": "SS student — Literature, JAMB, Enugu", "msgs": ["1","1","YES","Nkechi Obi","4","Literature","1","Enugu","5554","5554"]},
    {"desc": "SS student — Commerce, WAEC, Abia", "msgs": ["1","2","YES","Adaobi Eze","5","Commerce","2","Abia","5555","5555"]},
    {"desc": "SS student — Accounting, NECO, Osun", "msgs": ["1","1","YES","Tola Shola","5","Accounting","3","Osun","5556","5556"]},

    # JSS PATHS
    {"desc": "JSS2 student — Maths, Lagos", "msgs": ["1","1","YES","Mary John","2","Maths","Lagos","3434","3434"]},
    {"desc": "JSS1 student — science, Kano", "msgs": ["1","1","YES","Amina Bello","1","science","Kano","1112","1112"]},
    {"desc": "JSS3 student — basic science, Abuja", "msgs": ["1","1","YES","Junior Senior","3","basic science","Abuja","5853","5853"]},
    {"desc": "JSS2 student — English, Delta", "msgs": ["1","1","YES","Blessing Okoro","2","English","Delta","5855","5855"]},

    # TYPOS
    {"desc": "Typo: 'rnglish' → English", "msgs": ["1","1","YES","Grace Peter","4","rnglish","1","Lagos","1113","1113"]},
    {"desc": "Typo: 'chemstry' → Chemistry", "msgs": ["1","1","YES","John Doe","5","chemstry","2","Rivers","1114","1114"]},
    {"desc": "Typo: 'physcs' → Physics", "msgs": ["1","1","YES","Ada Nneka","4","physcs","1","Kaduna","1115","1115"]},
    {"desc": "Typo: 'goverment' → Government", "msgs": ["1","1","YES","Ibrahim Musa","5","goverment","2","Kano","1116","1116"]},
    {"desc": "Typo: 'biolgy' → Biology", "msgs": ["1","1","YES","Sarah John","4","biolgy","1","Delta","1117","1117"]},
    {"desc": "Typo: 'econmics' → Economics", "msgs": ["1","1","YES","Bola Tinubu","5","econmics","2","Lagos","1118","1118"]},
    {"desc": "Typo: 'litrature' → Literature", "msgs": ["1","1","YES","Arts Student","5","litrature","2","Ogun","1119","1119"]},
    {"desc": "Typo: 'commrce' → Commerce", "msgs": ["1","1","YES","Biz Student","5","commrce","1","Abia","1120","1120"]},
    {"desc": "Typo: 'accouting' → Accounting", "msgs": ["1","1","YES","Money Man","5","accouting","2","Osun","1121","1121"]},

    # NUMBER CONFUSION
    {"desc": "Types '1' instead of subject", "msgs": ["1","1","YES","Blessing Okafor","3","1","Lagos","1117","1117"]},
    {"desc": "Types '2' instead of subject", "msgs": ["1","1","YES","Femi Ade","5","2","Lagos","1118","1118"]},
    {"desc": "Types '3' instead of subject", "msgs": ["1","1","YES","Number Three","4","3","1","Lagos","1119","1119"]},

    # I DON'T KNOW
    {"desc": "Says 'I don't know' for subject", "msgs": ["1","1","YES","Chioma Nwosu","3","i don't know","Lagos","1121","1121"]},
    {"desc": "Says 'idk' for subject", "msgs": ["1","1","YES","Peter Obi","4","idk","1","Anambra","1122","1122"]},
    {"desc": "Says 'all of them' for subject", "msgs": ["1","1","YES","Obinna Okeke","4","all of them","1","Abuja","1123","1123"]},
    {"desc": "Says 'not sure' for subject", "msgs": ["1","1","YES","Esther James","3","not sure","Lagos","1124","1124"]},
    {"desc": "Says 'everything' for subject", "msgs": ["1","1","YES","All Student","4","everything","1","Lagos","1125","1125"]},

    # STATE VALIDATION
    {"desc": "Short state 'Ka' → rejected then 'Kano'", "msgs": ["1","1","YES","Ngozi Eze","4","English","1","Ka","Kaduna","1126","1126"]},
    {"desc": "Short state 'La' → rejected then 'Lagos'", "msgs": ["1","1","YES","Tunde Bello","4","Maths","1","La","Lagos","1127","1127"]},
    {"desc": "Full state 'FCT' accepted", "msgs": ["1","1","YES","Abuja Girl","4","English","1","FCT","5846","5846"]},

    # WEAK PINS
    {"desc": "Tries '1234' then valid PIN", "msgs": ["1","1","YES","Joy Adamu","4","Physics","1","Lagos","1234","5824","5824"]},
    {"desc": "Tries '0000' then valid PIN", "msgs": ["1","1","YES","Faith Okoro","4","Biology","1","Abuja","0000","4729","4729"]},
    {"desc": "Tries '1111' then valid PIN", "msgs": ["1","1","YES","Weak Picker","4","Maths","1","Kano","1111","9991","9991"]},
    {"desc": "Tries '9999' (not in weak set)", "msgs": ["1","1","YES","Lazy Picker","4","Chemistry","1","Lagos","9999","9999"]},

    # PIN MISMATCH
    {"desc": "Mismatches PIN once", "msgs": ["1","1","YES","Victor Eze","4","Economics","1","Lagos","5678","5679","5678","5678"]},
    {"desc": "Mismatches PIN twice", "msgs": ["1","1","YES","Double Wrong","4","Physics","1","Lagos","1234","5678","5679","1234","1234"]},

    # TERMS DECLINE
    {"desc": "Declines — just looking (3)", "msgs": ["1","1","no","3"]},
    {"desc": "Declines — don't understand (1)", "msgs": ["1","1","no","1"]},
    {"desc": "Declines — uncomfortable (2)", "msgs": ["1","1","no","2"]},
    {"desc": "Declines — decide later (4)", "msgs": ["1","1","no","4"]},

    # TERMS VARIATIONS
    {"desc": "Says 'Yep' to terms", "msgs": ["1","2","yep","Chidi Eze","5","Commerce","1","Lagos","4441","4441"]},
    {"desc": "Says 'Yeah' to terms", "msgs": ["1","1","yeah","Nkechi Obi","4","Literature","1","Enugu","4442","4442"]},
    {"desc": "Says 'Sure' to terms", "msgs": ["1","3","sure","Kemi Ade","4","Government","1","Oyo","4443","4443"]},
    {"desc": "Says 'Yup' to terms", "msgs": ["1","1","yup","Tola Bello","4","Biology","2","Kwara","4444","4444"]},

    # NAME VALIDATION
    {"desc": "Single name then full", "msgs": ["1","1","YES","David","David Emmanuel","4","Physics","1","Lagos","3334","3334"]},
    {"desc": "Short name 'A B' then full", "msgs": ["1","1","YES","A B","Amina Bello","3","Maths","Lagos","3335","3335"]},
    {"desc": "Fake name 'Wa' then full", "msgs": ["1","1","YES","Wa","Chidera Emeka","4","Physics","1","Lagos","3336","3336"]},

    # SUBJECT ABBREVIATIONS
    {"desc": "Types 'phy' → Physics", "msgs": ["1","1","YES","Uche Nnadi","4","phy","1","Imo","5551","5551"]},
    {"desc": "Types 'econ' → Economics", "msgs": ["1","1","YES","Bola Jr","5","econ","2","Lagos","5552","5552"]},
    {"desc": "Types 'bio' → Biology", "msgs": ["1","1","YES","Sarah J","4","bio","1","Delta","5553","5553"]},
    {"desc": "Types 'govt' → Government", "msgs": ["1","1","YES","Musa I","5","govt","2","Sokoto","5554","5554"]},
    {"desc": "Types 'comm' → Commerce", "msgs": ["1","1","YES","Ada Eze","5","comm","1","Abia","5555","5555"]},
    {"desc": "Types 'math' → Mathematics", "msgs": ["1","1","YES","Math Guy","4","math","1","Lagos","5557","5557"]},
    {"desc": "Types 'chem' → Chemistry", "msgs": ["1","1","YES","Chem Girl","4","chem","1","Lagos","5558","5558"]},

    # RETURNING USER PATHS
    {"desc": "Returning → WAX ID → changes mind to new", "msgs": ["2","YES","new","1","YES","Chidera Okonkwo","4","Biology","1","Enugu","5559","5559"]},
    {"desc": "Returning → WAX ID → valid format → then NEW", "msgs": ["2","YES","WAX-A74892","new","1","YES","Returning New","5","Physics","2","Lagos","5560","5560"]},
    {"desc": "Returning → invalid WAX ID → then NEW", "msgs": ["2","YES","myaccount","NEW","1","YES","Forgot ID","4","Maths","1","Lagos","5561","5561"]},

    # EDGE CASES
    {"desc": "Unclear first message then new", "msgs": ["hello","1","1","YES","Zainab Usman","4","Maths","1","Kogi","6661","6661"]},
    {"desc": "Types 'all' for subject", "msgs": ["1","1","YES","Esther James","3","all","Lagos","6664","6664"]},
    {"desc": "Unknown subject gets warm fallback", "msgs": ["1","1","YES","Precious Akpan","4","Yoruba","1","Lagos","6663","6663"]},
    {"desc": "Types with extra spaces and mixed case", "msgs": [" 1 "," 1 "," YES ","  dAvId  EmMaNuEl  ","4","pHysICs","1","lagos","5841","5841"]},
    {"desc": "JSS1 types 'basic science' full", "msgs": ["1","1","YES","Young One","1","basic science","Lagos","5854","5854"]},
]


# ── Main Runner ───────────────────────────────
async def run_all_scenarios():
    global captured_messages
    all_problems = []
    results = []
    total = len(SCENARIOS)
    passed = 0
    failed = 0

    for i, scenario in enumerate(SCENARIOS):
        captured_messages = []
        chat_id = 10000 + i
        desc = scenario["desc"]

        runner = ScenarioRunner(chat_id, scenario["msgs"])
        responses = await runner.run()
        problems = scan_for_problems(responses, desc)

        result = {
            "scenario": desc,
            "passed": len(problems) == 0,
            "problems": problems,
            "response_count": len(responses),
            "last_responses": [r["text"][:150] for r in responses[-3:]]
        }
        results.append(result)

        if problems:
            failed += 1
            all_problems.append({"scenario": desc, "problems": problems, "responses": [r["text"] for r in responses]})
        else:
            passed += 1

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "total": total,
        "passed": passed,
        "failed": failed,
        "results": results,
        "problems": all_problems
    }
