"""
WaxPrep v2 — Message Generator
Generates sequences of messages based on student profiles.
Mixes scripted messages with AI-simulated responses.
"""

import random


def generate_message_sequence(student_profile: dict, num_messages: int = 10) -> list:
    """
    Generate a sequence of messages for a student profile.
    
    Args:
        student_profile: Dict from student_profiles.py
        num_messages: How many messages to generate
    
    Returns:
        List of message strings
    """
    messages = [student_profile["initial_message"]]
    
    follow_ups = student_profile.get("follow_ups", [])
    
    for _ in range(num_messages - 1):
        if follow_ups:
            # 70% chance of using a follow-up, 30% chance of random
            if random.random() < 0.7:
                messages.append(random.choice(follow_ups))
            else:
                messages.append(_generate_random_message())
        else:
            messages.append(_generate_random_message())
    
    return messages


def _generate_random_message() -> str:
    """Generate a random student-like message for chaos testing."""
    chaos_messages = [
        "explain this again",
        "I don't get it",
        "what?",
        "can you give me an example",
        "how does this relate to JAMB",
        "is this in the syllabus",
        "give me a past question",
        "I think I understand now",
        "actually no I don't",
        "what's the formula",
        "can you summarize",
        "too long, make it shorter",
        "hmm",
        "interesting",
        "ok continue",
        "wait go back",
        "what was that first part",
        "how do you know that",
        "are you sure",
        "my teacher said something different",
    ]
    return random.choice(chaos_messages)


def generate_stress_test_messages() -> list:
    """Generate rapid-fire, chaotic messages for stress testing."""
    return [
        "hi",
        "explain osmosis",
        "wait no explain diffusion",
        "actually what's biology",
        "😂",
        "",
        " ",
        "give me test",
        "you pick",
        "I'm confused",
        "never mind I get it",
        "JAMB is tomorrow help",
        "how do I calculate this",
        "you're wrong",
        "you're right",
        "what's 2+2",
        "explain quantum physics",
        "what's your name",
        "who made you",
        "bye",
        "hello again",
        "I want to die",
        "how to cheat",
    ]
