"""P-008 readout over SYNTHETIC diary rows (never the real logs). No network, no writes into the repo."""
import json
import subprocess
import sys
from pathlib import Path

from oku_slack.world import report as R

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_790_000_000.0
DAY = 86400.0


def _row(i, typ, source, ts, actor=None, subject=None, payload=None, parents=None, regime="B_abundant"):
    return {"id": f"we_{i:04d}", "seq": i, "ts": ts, "type": typ, "source": source, "actor": actor,
            "subject": subject, "dedupe_key": None, "payload": payload or {}, "causal_parents": parents or [],
            "regime": regime, "content_version": "test", "run_id": "test"}


def _rows():
    return [
        _row(1, "agent.posted", "podnet", T0, "babis", "post:a", {"top_level": True, "brief_chars": 120}),
        _row(2, "agent.posted", "chatter", T0 + 60, "marty", "post:b", {"brief_chars": 0}),
        _row(3, "porada.requested", "schedule", T0 + DAY, "alenka", "porada:1", {}),
        _row(4, "agent.posted", "podnet", T0 + 2 * DAY, "babis", "post:c", {"top_level": False}),
        _row(5, "reaction", "slack", T0 + 120, "kuba", "post:a", {"polarity": "positive"}),
        _row(6, "reaction", "slack", T0 + 300, "lenka", "post:a", {}),
        _row(7, "reaction", "slack", T0 + 2 * DAY + 10, "kuba", "post:c", {}),
        _row(8, "budget.denied", "budget", T0 + 3 * DAY, None, "chatter:x", {"reasons": ["kill_switch:file"]}),
        _row(9, "bridge.reply", "bridge", T0 + 3 * DAY + 5, "babis", "slack:C1:1.0",
             {"llm_calls": 1, "est_usd": 0.002}),
        _row(10, "bridge.reply", "bridge", T0 + 3 * DAY + 6, "babis", None,
             {"llm_calls": 1, "est_usd": "UNKNOWN", "backend": "template"}),
        _row(11, "wheel.live", "wheel", T0 + 4 * DAY, None, "wheel:1", {}),
        _row(12, "wheel.expired", "wheel", T0 + 4 * DAY + 1, None, "wheel:2", {}),
    ]


def test_counts_over_fixed_rows():
    rep = R.build_report(_rows(), now=T0 + 4 * DAY + 1)
    assert rep["rows"] == 12
    assert rep["posts"] == 3  # the top_level False post is not counted
    assert rep["sources"]["bridge"] == 2
    assert rep["llm"]["calls"] == 2
    assert rep["llm"]["est_usd"] == 0.002
    assert rep["llm"]["fallbacks"] == 1
    assert rep["period"]["days"] == 5


def test_hypotheses_present_and_numeric():
    rep = R.build_report(_rows(), now=T0 + 4 * DAY + 1)
    h = rep["hypotheses"]
    assert set(h) == {"H1", "H2", "H3", "H4", "H5", "H6"}
    for k, v in h.items():
        assert isinstance(v["metric"], str) and v["metric"]
        assert isinstance(v["value"], (int, float)) and not isinstance(v["value"], bool)
    assert h["H1"]["by_source"]["real_life"]["responses"] == 2
    assert h["H2"]["value"] == 0.5  # 1 positive of 2 reactions on the post that carried a brief
    assert h["H3"]["count"] == 1
    assert h["H5"]["value"] == 2.0  # active human days: day 0 and day 2
    assert h["H6"]["value"] == 0.5  # 1 live of 2 rounds


def test_empty_rows_valid_report():
    rep = R.build_report([])
    assert rep["period"]["days"] == 0
    assert rep["rows"] == 0 and rep["posts"] == 0
    for v in rep["hypotheses"].values():
        assert v["value"] == 0.0
    assert "H6" in R.report_text(rep)


def test_causal_chain_walks_parents_and_survives_missing_parent():
    rows = [
        _row(1, "podnet.received", "podnet", T0),
        _row(2, "agent.posted", "podnet", T0 + 10, parents=["we_0001", "we_9999"]),
        _row(3, "consequence.applied", "consequence", T0 + 20, parents=["we_0002"]),
    ]
    chain = R.causal_chain(rows, "we_0003")
    assert [r["id"] for r in chain] == ["we_0001", "we_0002", "we_0003"]
    assert R.causal_chain(rows, "we_nope") == []


def test_markdown_has_six_hypothesis_labels():
    text = R.report_text(R.build_report(_rows(), now=T0 + 4 * DAY + 1))
    for k in ("H1", "H2", "H3", "H4", "H5", "H6"):
        assert f"**{k}**" in text


def test_load_rows_skips_half_written_line(tmp_path):
    (tmp_path / "world.jsonl").write_text(json.dumps(_rows()[0]) + "\n" + '{"id": "we_0002", "ts"', encoding="utf-8")
    assert len(R.load_rows(tmp_path)) == 1
    assert R.load_rows(tmp_path / "missing") == []


def test_cli_help_runs():
    out = subprocess.run([sys.executable, "-m", "oku_slack.world.report", "--help"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "--days" in out.stdout
