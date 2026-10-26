import numpy as np

from buds_assistant.eval.speaker_bench import evaluate


def vec(i, noise=0.04, seed=0):
    v = np.zeros(64, dtype=np.float32)
    v[i] = 1.0
    return v + noise * np.random.default_rng(seed).standard_normal(64).astype(np.float32)


def test_bench_gate_pass_and_stranger_rejection():
    embs = {"Alice_enrol": [vec(0, seed=1), vec(0, seed=2)], "Bob_enrol": [vec(1, seed=3), vec(1, seed=4)],
            "Alice_0.5m": [vec(0, seed=i) for i in range(10, 16)], "Bob_1m": [vec(1, seed=i) for i in range(20, 26)],
            "stranger_Cy_1m": [vec(5, seed=i) for i in range(30, 36)]}
    r = evaluate(embs, 0.62)
    assert r["gate_passed"] and r["accuracy"] == 1.0 and r["stranger_false_accept"] == 0.0
    assert set(r["per_condition"]) == {"Alice_0.5m", "Bob_1m"} and r["speakers"] == ["Alice", "Bob"]
    assert len(r["sweep"]) >= 10


def test_bench_fails_when_voices_overlap():
    embs = {"Alice_enrol": [vec(0, 0.04, 1)], "Bob_enrol": [vec(1, 0.04, 2)],
            "Alice_1m": [vec(1, 0.04, i) for i in range(10, 16)],                    # Alice's clips sound like Bob
            "stranger_Cy_1m": [vec(0, 0.04, i) for i in range(30, 36)]}              # a stranger sounds like Alice
    r = evaluate(embs, 0.62)
    assert not r["gate_passed"] and r["stranger_false_accept"] > 0.5
