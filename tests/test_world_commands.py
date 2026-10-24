"""`/oku` command layer: parse table, renderers on synthetic data, and handle() with an injected fake fetch.
No network and no writes."""
from oku_slack.world import commands as C


def test_parse_table():
    assert C.parse("/oku svet") == ("svet", [])
    assert C.parse("/oku denik 20") == ("denik", ["20"])
    assert C.parse("/oku proc we_0007") == ("proc", ["we_0007"])
    assert C.parse("/oku ticho 2") == ("ticho", ["2"])
    assert C.parse("/oku nahlas") == ("nahlas", [])
    assert C.parse("/oku podnet https://example.test/v") == ("podnet", ["https://example.test/v"])
    assert C.parse("/oku rezim B") == ("rezim", ["B"])
    assert C.parse("/oku slib jedna dvě") == ("slib", ["jedna", "dvě"])


def test_parse_aliases_case_spacing_and_unknown():
    assert C.parse("/oku svět")[0] == "svet"
    assert C.parse("/OKU   Svět  ") == ("svet", [])
    assert C.parse("/oku") == ("svet", [])
    assert C.parse("/oku neexistuje") == ("unknown", [])
    assert C.parse("svet") == ("unknown", [])
    assert C.parse("") == ("unknown", [])
    assert C.parse(None) == ("unknown", [])


def test_commands_contract():
    for k in ("svet", "denik", "proc", "ticho", "nahlas", "podnet", "rezim", "slib"):
        assert k in C.COMMANDS and C.COMMANDS[k]


def test_render_svet_has_regime_and_every_resource():
    snap = {"regime": "A_scarce", "resources": {"dotace": 5000, "kampan": 60, "hranolky": 80, "lajky": 1200, "novy": 7},
            "blame": {"babis": 3}, "metrics_7d": {"spun": 10, "live": 4, "human_actions": 2, "bridge_calls": 5}}
    out = C.render_svet(snap)
    assert isinstance(out, str)
    assert C.REGIMES["A_scarce"] in out
    for k in ("5 000", "60", "80", "1 200", "7"):
        assert k in out
    assert "Dotace" in out and "novy" in out
    assert C.render_svet({}).startswith("🌍")


def _rows():
    return [
        {"seq": 1, "id": "we_0001", "ts": 100, "type": "wheel.spin", "actor": "babis", "subject": "kantyna",
         "causal_parents": [], "payload": {"why": ["cooldown ok", "budget ok"], "text": "SECRET_TEXT_ONE"}},
        {"seq": 2, "id": "we_0002", "ts": 200, "type": "podnet.react", "actor": "marty", "subject": "video",
         "causal_parents": ["we_0001"], "payload": {"why": ["ok"], "candidates": ["a", "b"], "rng_key": "PODNET:x",
                                                    "opener": "SECRET_TEXT_TWO"}},
        {"seq": 3, "id": "we_0003", "ts": 300, "type": "lajky.delta", "actor": "system", "subject": "lajky",
         "causal_parents": ["we_0002"], "payload": {"delta": 5}},
    ]


def test_render_denik_no_payload_text_leaks():
    out = C.render_denik(_rows(), 20)
    assert "we_0001" in out and "we_0003" in out
    assert "podnet.react" in out and "marty" in out
    assert "SECRET_TEXT_ONE" not in out and "SECRET_TEXT_TWO" not in out
    assert "(obsah vynechán)" in out
    assert C.render_denik([], 20).startswith("📖")
    assert len(C.render_denik(_rows(), 1).splitlines()) == 2  # header + one row


def test_render_proc_chain_oldest_first_with_reasons():
    out = C.render_proc(_rows(), "we_0003")
    body = out.splitlines()[1:]
    assert [l.split("`")[1] for l in body] == ["we_0001", "we_0002", "we_0003"]
    assert body[-1].startswith("▶ `we_0003`")
    assert "kandidáti 2" in out and "PODNET:x" in out
    assert "SECRET_TEXT" not in out
    assert "nenalezen" in C.render_proc(_rows(), "we_9999")
    assert isinstance(C.render_proc([], "we_1"), str)


def test_render_proc_survives_cycle():
    rows = [{"id": "a", "ts": 1, "type": "t", "causal_parents": ["b"], "payload": {}},
            {"id": "b", "ts": 2, "type": "t", "causal_parents": ["a"], "payload": {}}]
    body = C.render_proc(rows, "a").splitlines()[1:]
    assert [l.split("`")[1] for l in body] == ["b", "a"]


def test_handle_with_fake_fetch_no_http():
    calls = []

    def fake(path, query):
        calls.append((path, query))
        if query.get("events") == 500 or query.get("events") == 3:
            return {"events": _rows()}
        return {"regime": "B_abundant", "resources": {"dotace": 1}}

    assert C.REGIMES["B_abundant"] in C.handle("/oku svet", fetch=fake)
    assert "we_0003" in C.handle("/oku denik 3", fetch=fake)
    assert "Příčinný" in C.handle("/oku proc we_0003", fetch=fake)
    assert "Použij" in C.handle("/oku proc", fetch=fake)
    assert "Použij" in C.handle("/oku denik abc", fetch=fake)
    assert "Neznámý" in C.handle("/oku neexistuje", fetch=fake) and "/oku svet" in C.handle("/oku x", fetch=fake)
    assert "další fázi" in C.handle("/oku ticho 2", fetch=fake)
    assert calls and all(p == "/api/world" for p, _ in calls)


def test_handle_never_raises_and_reports_down():
    def boom(path, query):
        raise OSError("down")

    assert C.handle("/oku svet", fetch=boom).startswith("🌍")
    assert C.handle("/oku denik", fetch=lambda p, q: None).startswith("🌍")
    assert C.handle("/oku proc we_1", fetch=lambda p, q: None).startswith("🌍")
