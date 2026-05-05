"""
WaxPrep v2 — Magic Trick Subject Hooks
Hand-crafted, instant-response hooks that prove WaxPrep's value
before collecting full profile details.

Each subject has a hook for SS (Senior Secondary) and JSS (Junior Secondary).
The hook follows a 4-part structure:
  1. Acknowledge the feeling
  2. One simple concept
  3. Nigerian example
  4. Hope + transition
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MagicTrick:
    subject: str
    level: str  # "SS" or "JSS"
    hook: str
    concept: str
    example: str
    transition: str

    def render(self) -> str:
        """Return the full formatted Magic Trick message."""
        return f"{self.hook}\n\n{self.concept}\n\n{self.example}\n\n{self.transition}"


# ──────────────────────────────────────────────
# SUBJECT ALIASES — catch typos, abbreviations, street names
# ──────────────────────────────────────────────

SUBJECT_ALIASES = {
    # Physics
    "physic": "Physics", "phy": "Physics", "physics": "Physics",
    # Mathematics
    "maths": "Mathematics", "math": "Mathematics", "mathematics": "Mathematics",
    "further maths": "Further Mathematics", "further math": "Further Mathematics",
    # Chemistry
    "chem": "Chemistry", "chemistry": "Chemistry",
    # Biology
    "bio": "Biology", "biology": "Biology",
    # Economics
    "econ": "Economics", "economics": "Economics", "economic": "Economics",
    # Government
    "govt": "Government", "government": "Government", "gov": "Government",
    # English
    "eng": "English", "english": "English", "english language": "English",
    # Literature
    "lit": "Literature", "literature": "Literature",
    "literature in english": "Literature", "lit-in-english": "Literature",
    # Commerce
    "comm": "Commerce", "commerce": "Commerce",
    # Accounting
    "account": "Accounting", "accounting": "Accounting",
    "fin account": "Accounting", "financial accounting": "Accounting",
    # Agricultural Science
    "agric": "Agricultural Science", "agriculture": "Agricultural Science",
    "agricultural science": "Agricultural Science", "agri": "Agricultural Science",
    # Geography
    "geo": "Geography", "geography": "Geography",
    # Civic Education
    "civic": "Civic Education", "civic education": "Civic Education",
    # CRS / IRS
    "crs": "Christian Religious Studies", "christian religious studies": "Christian Religious Studies",
    "irs": "Islamic Religious Studies", "islamic religious studies": "Islamic Religious Studies",
    # JSS names
    "science": "Basic Science", "basic science": "Basic Science",
    "basic math": "Basic Mathematics", "basic maths": "Basic Mathematics",
    "basic mathematics": "Basic Mathematics",
}

# Subjects we have full hooks for (SS level)
READY_SS_SUBJECTS = {
    "Physics", "Mathematics", "Chemistry", "Biology",
    "Economics", "Government", "English", "Literature",
    "Commerce", "Accounting",
}

# Subjects we have full hooks for (JSS level)
READY_JSS_SUBJECTS = {
    "Basic Science", "Basic Mathematics",
}

# Subjects we recognize but don't have full hooks for yet
RECOGNIZED_SUBJECTS = {
    "Further Mathematics", "Agricultural Science", "Geography",
    "Civic Education", "Christian Religious Studies", "Islamic Religious Studies",
}


# ──────────────────────────────────────────────
# MAGIC TRICKS — SS LEVEL
# ──────────────────────────────────────────────

SS_MAGIC_TRICKS = {
    "Physics": MagicTrick(
        subject="Physics",
        level="SS",
        hook="Ah, Physics. Most students run from it — but here's the thing: you already do Physics every single day.",
        concept="Physics is simply the rules of how things move and work. When something moves, stops, speeds up, or changes direction — that's Physics in action.",
        example="You know when a danfo bus brakes suddenly and everyone jerks forward? That's inertia — your body wants to keep moving even when the bus stops. You didn't need a textbook to feel it. You already understand Physics — you just didn't know the name.",
        transition="Once we set up your profile, I'll show you how to use this everyday understanding to crush Physics in your exam. Now let's get you set up.",
    ),
    "Mathematics": MagicTrick(
        subject="Mathematics",
        level="SS",
        hook="Math feels like a puzzle you didn't ask to solve. But truth is — you're already doing Math every time you spend money.",
        concept="Math is just patterns and relationships. When you see a pattern — like prices going up or down, or numbers repeating — you're thinking mathematically.",
        example="A suya seller doesn't use a calculator to give you change. She knows: you gave 500 naira, suya is 350, change is 150. That's algebra — she solved '500 - x = 350' in her head without writing a single line.",
        transition="Math is street sense given a fancy name. Let's build your profile so I can show you how to bring that street sense into the exam hall.",
    ),
    "Chemistry": MagicTrick(
        subject="Chemistry",
        level="SS",
        hook="Chemistry looks like cooking with invisible ingredients. But you've been a chemist since you were small.",
        concept="Chemistry is the study of what things are made of and how they change when you mix them. Every time something bubbles, rises, burns, or dissolves — Chemistry is happening.",
        example="When you make puff-puff and add baking soda, the dough rises. That's a chemical reaction — the baking soda releases gas when it meets the hot oil, and those gas bubbles make the puff-puff soft and fluffy. You're not just frying — you're running a chemistry experiment.",
        transition="See? You're already a chemist in the kitchen. Let's set up your profile and I'll connect the dots to your syllabus.",
    ),
    "Biology": MagicTrick(
        subject="Biology",
        level="SS",
        hook="Biology is the study of life itself. And you live inside a Biology classroom every single day.",
        concept="Biology explains how living things work — from your own body breathing and digesting, to the mosquito that bites you at night, to the beans swelling in water before you cook them.",
        example="When you soak egusi seeds or beans before cooking, they swell up. That's osmosis — water moving into the seed because the inside of the seed is more concentrated. You've seen this your whole life. Now you know the name.",
        transition="Your own body is a biology lab. Let's build your profile and I'll show you how to use what you already know to pass your exam.",
    ),
    "Economics": MagicTrick(
        subject="Economics",
        level="SS",
        hook="Economics sounds like big men in suits discussing naira and dollars. But you already understand Economics better than you think.",
        concept="Economics is simply the study of choices — what people buy, what they sell, and why prices go up and down. Every time you make a decision with limited money, you're an economist.",
        example="Notice how tomato prices double during rainy season? That's supply and demand. Fewer tomatoes reach the market (low supply) but everyone still wants stew (high demand) — so prices shoot up. You already track this without realizing it.",
        transition="Economics is your daily life given a name. Let's set up your profile and I'll show you how to use what you already know to ace the exam.",
    ),
    "Government": MagicTrick(
        subject="Government",
        level="SS",
        hook="Government feels like learning about people in big offices who don't affect your life. But Government is actually happening around you right now.",
        concept="Government is the study of how power is organized and used. Who makes decisions? Who enforces them? Why do we have a President AND a Governor? These are the questions Government answers.",
        example="Think about INEC and elections. When you vote (or watch adults vote), you're seeing Government in action. The President runs the whole country. Your Governor runs just your state. They have different powers — that's called separation of powers. You already observe this during every election season.",
        transition="Government is just the rules of how Nigeria works. Let's set up your profile and I'll make it make sense.",
    ),
    "English": MagicTrick(
        subject="English",
        level="SS",
        hook="English doesn't need big grammar to be good English. In fact, the best writers keep it simple.",
        concept="Good English is about clarity — making sure the person reading or listening understands exactly what you mean. It's not about big words. It's about clear thinking.",
        example="Chinua Achebe wrote 'Things Fall Apart' — one of the world's greatest novels — in simple, clear English. He didn't use 'commence' when 'start' would do. He didn't say 'utilize' when 'use' was clearer. Your English exam tests your understanding, not your vocabulary.",
        transition="Clear thinking, not big grammar. Let's build your profile and I'll show you how to apply this in your exam.",
    ),
    "Literature": MagicTrick(
        subject="Literature",
        level="SS",
        hook="Literature can feel like looking for hidden meanings that aren't there. But here's the truth: all stories work the same way.",
        concept="Every story has a surface (the plot — what happens) and a depth (the theme — what it means). The author uses characters, settings, and events to explore bigger ideas about life, power, love, or change.",
        example="In 'Things Fall Apart', the plot is about Okonkwo's rise and fall. But the theme is about what happens when an old world meets a new one — which is something Nigeria is still experiencing today. Once you see the difference between plot and theme, every book opens up.",
        transition="Stories are mirrors — they reflect real life. Let's set up your profile and I'll show you how to read like a detective.",
    ),
    "Commerce": MagicTrick(
        subject="Commerce",
        level="SS",
        hook="Commerce sounds like big business in skyscrapers. But it's actually happening in every market, every kiosk, every street corner around you.",
        concept="Commerce is the study of trade — how goods move from producers to consumers. Every time someone makes something, transports it, sells it, or buys it, that's Commerce.",
        example="A keke napep driver buys fuel from a filling station (trade), uses it to transport passengers (service), and earns money (profit). He's not just driving — he's running a commerce operation. Production, distribution, consumption — you see all three on one street.",
        transition="Commerce is the lifeblood of every Nigerian street. Let's build your profile and I'll connect it to your syllabus.",
    ),
    "Accounting": MagicTrick(
        subject="Accounting",
        level="SS",
        hook="Accounting looks like boring numbers in big ledgers. But you already do Accounting — every time you track your money.",
        concept="Accounting is simply keeping track of what comes in and what goes out. Income. Expenses. Balance. When you know exactly how much you have and where it went, you're doing Accounting.",
        example="Think about your personal budget. You got 2,000 naira. You spent 500 on data, 300 on transport, 200 on snacks. You have 1,000 left. That's a simple income statement and balance sheet — the core of Accounting. You already do this in your head.",
        transition="Accounting is just organized common sense. Let's set up your profile and I'll show you how to apply this to your exam.",
    ),
}


# ──────────────────────────────────────────────
# MAGIC TRICKS — JSS LEVEL
# ──────────────────────────────────────────────

JSS_MAGIC_TRICKS = {
    "Basic Science": MagicTrick(
        subject="Basic Science",
        level="JSS",
        hook="Science sounds big — but it's really just paying attention to how things around you work.",
        concept="Science asks two questions: 'What happens?' and 'Why does it happen?' You ask these questions every day without realizing it.",
        example="When you put a spoon in hot water, the spoon gets hot too. Why? Because heat travels from the hot water into the cooler spoon. That's heat transfer — and you've just done a science experiment in your kitchen.",
        transition="See? You're already a scientist. Let's build your profile and I'll show you more things you already understand.",
    ),
    "Basic Mathematics": MagicTrick(
        subject="Basic Mathematics",
        level="JSS",
        hook="Math isn't just about numbers on a board. It's about patterns — and you're already good at spotting patterns.",
        concept="Math helps you solve problems by finding patterns. When you figure out how much change you should get, or how to share things equally, you're doing Math.",
        example="You and 3 friends share 12 biscuits. Without thinking, you know each person gets 3. That's division — and you just solved a math problem faster than someone writing it on paper.",
        transition="Math is already in your head. Let's set up your profile and I'll help you bring it out.",
    ),
}


# ──────────────────────────────────────────────
# WARM FALLBACK — for subjects we don't have full hooks for yet
# ──────────────────────────────────────────────

FALLBACK_MESSAGE = (
    "Interesting choice! I don't have a special trick for that subject yet — "
    "but I'm adding new subjects every week. Yours might be next.\n\n"
    "In the meantime, you've got good instincts asking about it. "
    "Let's set up your profile and I'll help you with it anyway."
)


# ──────────────────────────────────────────────
# LOOKUP FUNCTION
# ──────────────────────────────────────────────

def normalize_subject(raw: str) -> str:
    """Convert user input to a standard subject name."""
    cleaned = raw.strip()
    # Try exact match first
    if cleaned in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[cleaned]
    # Try case-insensitive
    lower = cleaned.lower()
    if lower in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[lower]
    # Return as-is (might be an unrecognized subject)
    return cleaned


def get_magic_trick(subject_name: str, level: str) -> Optional[MagicTrick]:
    """
    Get the Magic Trick for a subject and level.
    Returns None if not found (use FALLBACK_MESSAGE).
    """
    # Try SS hooks
    if level in ("SS1", "SS2", "SS3", "SS"):
        if subject_name in SS_MAGIC_TRICKS:
            return SS_MAGIC_TRICKS[subject_name]
    # Try JSS hooks
    elif level in ("JSS1", "JSS2", "JSS3", "JSS"):
        if subject_name in JSS_MAGIC_TRICKS:
            return JSS_MAGIC_TRICKS[subject_name]
    return None


def get_subject_fallback(subject_name: str) -> str:
    """Return a warm fallback message specific to this subject."""
    if subject_name in RECOGNIZED_SUBJECTS:
        return (
            f"Ah, {subject_name}! I don't have a special trick for it yet — "
            f"but I'm adding new subjects every week and {subject_name} is on my list.\n\n"
            f"Let's set up your profile and I'll help you with it anyway."
        )
    return FALLBACK_MESSAGE
