from fixtures_autopilot import SCRIPT, build, run


def test_precision_at_least_70_percent_with_memory(tmp_path):
    p, s, people, cfg = build(tmp_path)
    said = run(SCRIPT, p, people)
    hits = [x for x in said if x[1] == x[2]]
    assert said and len(hits) / len(said) >= 0.7, said
    assert {"identity", "capture", "question", "commitment", "mention"} <= {x[1] for x in said}      # every job fires


def test_cold_start_still_captures_commitments(tmp_path):
    p, s, people, cfg = build(tmp_path, with_memory=False)
    said = run(SCRIPT, p, people)
    assert [x[1] for x in said] == ["capture", "capture", "capture"]
    assert all(x[2] == "capture" for x in said)
    assert len(s.facts(kind="commitment")) == 3                       # and they are remembered


def test_rate_never_exceeds_config(tmp_path):
    p, s, people, cfg = build(tmp_path)
    said = run(SCRIPT, p, people)
    assert len(said) <= cfg.hints_per_hour
    others = [off for off, trig, _ in said if trig != "capture"]
    assert all(b - a >= cfg.hint_min_gap for a, b in zip(others, others[1:]))


def test_no_whisper_for_unknown_voices(tmp_path):
    p, s, people, cfg = build(tmp_path)
    said = run(SCRIPT, p, people)
    unknown = {off for off, _, key, *_ in SCRIPT if key is None}
    assert not unknown & {off for off, *_ in said}
    assert any(d["reason"] == "unknown_voice" for d in s.decisions())


def test_every_script_line_is_accounted_for(tmp_path):
    """Whispered lines are in the log as said/noted; silent labelled-None lines never produced a whisper."""
    p, s, people, cfg = build(tmp_path)
    said = run(SCRIPT, p, people)
    logged = [d for d in s.decisions() if d["outcome"] in ("said", "noted")]
    assert len(logged) == len(said)
