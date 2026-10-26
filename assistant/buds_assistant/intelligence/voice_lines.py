"""Everything Sidekick says about itself, in one place: polite, warm, short (<= 12 words for whispers), first person.
Tune the wording here; tests keep every line short and a complete sentence."""
from __future__ import annotations


def promise_noted(task: str, due: str | None, to_do: bool, clash: str | None = None) -> str:
    when = f" for {due}" if due else ""
    base = f"I've added '{task}'{when} to your to-dos." if to_do else f"I've noted that you'll {task}{when}."
    return base + (f" Just so you know, you have {clash} then." if clash else "")


def clash_note(title: str) -> str:
    return f"Just so you know, you have {title} then."


def todo_added(task: str) -> str:
    return f"Done, I've added {task} to your to-dos."


def didnt_catch() -> str:
    return "Sorry, I didn't catch that. Could you say it again?"


def reminder(text: str) -> str:
    return f"A quick reminder: {text}."


def meeting_soon(title: str, minutes: int, who: str | None) -> str:
    return f"Your {title} starts in {minutes} minutes" + (f", with {who}." if who else ".")


def free_answer(label: str) -> str:
    return f"You're free {label}, shall I say yes?"


def unknown_voice() -> str:
    return "I don't recognise this voice yet."


def interpreter_on() -> str:
    return "Interpreter is on. I'll translate as they speak."


def model_down() -> str:
    return "I can't reach the language model right now. Quick commands still work."


def here() -> str:
    return "I'm here. How can I help?"
