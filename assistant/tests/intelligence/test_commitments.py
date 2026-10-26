import pytest

from buds_assistant.intelligence.commitments import detect


@pytest.mark.parametrize("text,expected_text,expected_due", [
    ("I'll send it Friday", "send it", "Friday"),
    ("I will call Anita tomorrow morning", "call Anita", "tomorrow"),
    ("Let me email the contract by Monday", "email the contract", "Monday"),
    ("I'm going to review the slides tonight", "review the slides", "tonight"),
    ("I will send you the report by Friday afternoon", "send you the report", "Friday"),
    ("I'll book the room", "book the room", None),
])
def test_detects_first_person_promises(text, expected_text, expected_due):
    c = detect(text)
    assert c and c.text == expected_text and c.due == expected_due


@pytest.mark.parametrize("text", ["I will be there on time", "I'll think about it", "He will send it Friday",
                                  "Did you send the report?", "I sent it yesterday", "we could maybe call",
                                  "Would you send it Friday?"])
def test_ignores_non_commitments(text):
    assert detect(text) is None
