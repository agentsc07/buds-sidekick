import pytest

from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.speech.translate import Translator, _chunks, detect_lang

TE = "రేపు మన సమావేశం ఉంటుంది"


def test_detect_lang():
    assert detect_lang("hello there") == "en" and detect_lang(TE) == "te"
    assert detect_lang("meeting రేపు సమావేశం ఉంటుంది") == "te"          # majority script wins
    assert detect_lang("1234 !!") == "unknown"


def test_translate_routes_and_prompt():
    llm = FakeLLM([TE])
    r = Translator(llm).translate("The meeting is tomorrow")
    assert r.ok and r.src == "en" and r.dst == "te" and r.text == TE
    p = llm.calls[0]["messages"][0]["content"]
    assert "Telugu" in p and "only the translation" in p and llm.calls[0]["model"] == "gemma4:12b-mlx"


def test_edge_inputs():
    t = Translator(FakeLLM(["x"]))
    assert not t.translate("   ").ok
    assert not t.translate("12345").ok
    assert not t.translate("hello", dst="fr").ok
    assert Translator(FakeLLM(up=False)).translate("hello").error.startswith("fake llm")     # model down: clean error
    assert not Translator(FakeLLM(["still english"])).translate("hello", dst="te").ok          # wrong-script reply rejected
    assert t.translate("hello", "en", "en").text == "hello"


def test_long_text_is_chunked_by_sentence():
    text = " ".join(f"This is sentence number {i} of a long passage." for i in range(40))
    chunks = _chunks(text)
    assert len(chunks) > 3 and all(len(c) <= 330 for c in chunks)
    llm = FakeLLM(lambda m, model: TE)
    assert Translator(llm).translate(text, "en", "te").ok and len(llm.calls) == len(chunks)


@pytest.mark.slow
def test_real_model_en_to_te():
    from buds_assistant.intelligence.llm import OllamaClient
    c = OllamaClient()
    if not c.available():
        pytest.skip("ollama not running")
    r = Translator(c).translate("Could you send me the budget report by Friday afternoon?", "en", "te")
    assert r.ok and detect_lang(r.text) == "te"
