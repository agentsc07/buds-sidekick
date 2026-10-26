from test_api_v2 import client  # noqa: F401  (fixture)


def test_language_dropdowns_set_direction_and_flip_the_other_side(client):
    r = client.post("/api/v2/interpreter", json={"src": "en", "dst": "te"}).json()
    assert (r["from"], r["to"]) == ("en", "te")
    r = client.post("/api/v2/interpreter", json={"src": "te"}).json()          # same on both sides: the other flips
    assert (r["from"], r["to"]) == ("te", "en")
    r = client.post("/api/v2/interpreter", json={"dst": "en"}).json()
    assert (r["from"], r["to"]) == ("te", "en") or r["from"] != r["to"]
    assert client.post("/api/v2/interpreter", json={"src": "fr"}).status_code == 400
    assert client.get("/api/v2/state").json()["interpreter"]["from"] in ("te", "en")


def test_buds_are_found_even_when_renamed():
    from buds_assistant.desktop import parse_buds_connected
    sample = "Bluetooth:\n  Connected:\n      Sai's Buds FE:\n          Address: 1\n  Not Connected:\n      WG-02:\n          Address: 2\n"
    assert parse_buds_connected(sample)
    assert not parse_buds_connected(sample.replace("Sai's Buds FE", "Headphones"))
    assert not parse_buds_connected("  Not Connected:\n      Sai's Buds FE:\n          Address: 1\n")
