"""The assistant's own voice is polite, short and in one place (docs/specs/spec-v3-ux.md section 6)."""
import re
import inspect

from buds_assistant.intelligence import voice_lines as v


def test_every_line_is_polite_short_and_a_sentence():
    lines = [
        v.promise_noted("send the report", "Friday", to_do=True, clash="Standup"), v.promise_noted("call mum", None, to_do=False),
        v.didnt_catch(), v.reminder("take medicine"), v.meeting_soon("Standup", 10, "Priya"), v.meeting_soon("Standup", 2, None),
        v.todo_added("buy milk"), v.unknown_voice(), v.interpreter_on(), v.model_down(), v.free_answer("tomorrow at 2"), v.clash_note("Standup"),
    ]
    for line in lines:
        assert len(line.split()) <= 20, line
        assert re.search(r"[.?!]$", line), line
        assert not line.startswith("Noted:") and "unknown_voice" not in line, line


def test_the_robotic_telegram_style_is_gone_from_the_code():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "buds_assistant"
    banned = ['"I did not catch that."', 'f"Noted: {c.text}"', '" Added to your to-do."', '" Heads up, ']
    for p in list(root.glob("*.py")):
        if p.name == "voice_lines.py":
            continue
        src = p.read_text()
        for b in banned:
            assert b not in src, (p.name, b)


def test_a_clash_and_a_to_do_are_mentioned_politely():
    t = v.promise_noted("send the report", "Friday", to_do=True, clash="Standup")
    assert "I've added" in t and "Friday" in t and "Standup" in t
