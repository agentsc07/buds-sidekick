import asyncio
from collections import deque

from buds_assistant.core.config import Config
from buds_assistant.speech.interpreter import Interpreter, Phrase


def phrase(lang, is_self=False, person_id=None):
    return Phrase("x", lang, 0.0, 1.0, "Speaker", person_id, is_self, 1.0, 0.0)


def interp(src, dst, two_way=False):
    it = Interpreter.__new__(Interpreter)               # only the direction rule is under test
    it.cfg = Config(interpreter_from=src, interpreter_to=dst, interpreter_two_way=two_way)
    return it


def test_default_is_their_telugu_in_my_english():
    it = interp("te", "en")
    assert it._direction(phrase("te")) == ("te", "en") and it._direction(phrase("en")) is None


def test_they_speak_english_i_hear_telugu_but_never_my_own_words():
    it = interp("en", "te")
    assert it._direction(phrase("en", person_id=None)) == ("en", "te")
    assert it._direction(phrase("en", is_self=True)) is None and it._direction(phrase("te")) is None


def test_same_language_both_sides_translates_nothing():
    assert interp("en", "en")._direction(phrase("en")) is None


def test_legacy_two_way_still_speaks_my_english_as_telugu():
    assert interp("te", "en", two_way=True)._direction(phrase("en", is_self=True)) == ("en", "te")
