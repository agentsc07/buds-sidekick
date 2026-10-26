from buds_assistant.core.config import Config
from buds_assistant.core.events import EventBus
from buds_assistant.intelligence.llm import FakeLLM
from buds_assistant.core.models import ModelManager


def swap_cfg():
    """A chat model different from the translator: the two are swapped in and out of memory (the old behaviour)."""
    return Config(chat_model="qwen3.5:4b-mlx", translate_model="gemma4:12b-mlx")


def test_chat_and_embed_ready_after_start():
    llm, ev = FakeLLM(), EventBus()
    m = ModelManager(llm, swap_cfg(), ev)
    assert m.state()["chat"] == "unloaded"
    m.start()
    assert m.state()["chat"] == "ready" and m.state()["embed"] == "ready" and m.state()["translate"] == "unloaded"


def test_interpreter_loads_translate_model_then_unloads():
    llm, ev, cfg = FakeLLM(), EventBus(), swap_cfg()
    m = ModelManager(llm, cfg, ev); m.start()
    m.enter("interpreter")
    assert m.state()["translate"] == "ready" and cfg.translate_model in llm.pinned
    assert llm.calls[-1]["model"] == cfg.translate_model and llm.calls[-1]["keep_alive"] == "30m"
    m.leave("interpreter")
    assert m.state()["translate"] == "unloaded" and cfg.translate_model not in llm.pinned
    assert [c for c in llm.calls if c["model"] == cfg.translate_model][-1]["keep_alive"] == "0"


def test_other_modes_do_not_touch_the_translation_model():
    llm, cfg = FakeLLM(), swap_cfg()
    m = ModelManager(llm, cfg, EventBus()); m.start()
    n = len(llm.calls)
    m.enter("autopilot"); m.leave("autopilot")
    assert len(llm.calls) == n and m.state()["translate"] == "unloaded"


def test_state_changes_are_published():
    ev = EventBus(); m = ModelManager(FakeLLM(), Config(), ev); m.start()
    assert ev.recent(types={"model_state"})


def test_llm_down_reports_unloaded_not_crash():
    ev = EventBus()
    m = ModelManager(FakeLLM(up=False), swap_cfg(), ev); m.start()
    assert m.state()["chat"] == "unloaded"
    m.enter("interpreter")
    assert m.state()["translate"] == "unloaded" and ev.recent(types={"error"})


def test_interpreting_frees_memory_by_unloading_the_chat_models_and_restores_them_after():
    llm, cfg = FakeLLM(), swap_cfg()
    m = ModelManager(llm, cfg, EventBus()); m.start()
    m.enter("interpreter")
    assert m.state()["chat"] == "unloaded" and m.state()["embed"] == "unloaded"             # a 16 GB Mac cannot hold all three
    assert llm.unloaded == [cfg.chat_model, cfg.embed_model]                # asked Ollama to drop them
    m.leave("interpreter")
    assert m.state()["chat"] == "ready" and m.state()["embed"] == "ready"


def test_everyday_models_load_by_themselves_once_ollama_comes_up():
    llm = FakeLLM(); llm.up = False
    m = ModelManager(llm, Config(), EventBus())
    m.start()
    assert m.state()["chat"] == "unloaded"
    m.ensure()                                                   # still down: nothing happens, nothing raised
    assert m.state()["chat"] == "unloaded"
    llm.up = True
    m.ensure()
    assert m.state()["chat"] == "ready" and m.state()["embed"] == "ready"


def test_ensure_leaves_models_alone_while_interpreting():
    llm = FakeLLM(); m = ModelManager(llm, swap_cfg(), EventBus()); m.start()
    m.enter("interpreter")                                       # chat/embed are unloaded on purpose here
    n = len(llm.calls)
    m.ensure()
    assert m.state()["chat"] == "unloaded" and len(llm.calls) == n


def test_one_model_for_everything_means_the_translator_is_ready_from_the_start():
    """A 16 GB Mac holds one big model, not two (Ollama evicts the other). gemma4 12B answers, judges and translates as well as the 4B model did,
    so with one resident model Translate needs no loading: clicking it is instant."""
    cfg = Config()
    assert cfg.chat_model == cfg.translate_model
    llm = FakeLLM(); m = ModelManager(llm, cfg, EventBus()); m.start()
    assert m.state()["chat"] == "ready" and m.state()["translate"] == "ready"
    n = len(llm.calls)
    m.enter("interpreter")
    assert len(llm.calls) == n and llm.unloaded == [] and m.state()["chat"] == "ready"        # nothing to load, nothing to unload
    m.leave("interpreter")
    assert len(llm.calls) == n and llm.unloaded == [] and m.state()["translate"] == "ready"


def test_the_speech_hooks_still_run_when_one_model_serves_everything():
    cfg, calls = Config(), []
    m = ModelManager(FakeLLM(), cfg, EventBus()); m.start()
    m.hooks = {"enter": lambda: calls.append("enter"), "leave": lambda: calls.append("leave")}
    m.enter("interpreter"); m.leave("interpreter")
    assert calls == ["enter", "leave"] and m.state()["telugu"] == "ready"
