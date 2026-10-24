"""OKÚ world readout (ECOSYSTEM-PLAN P-008): H1-H6, cost and causal chains from the diary.

Read-only over the diary rows (logs/world.jsonl). Never writes, deletes or re-keys a row. Stdlib only.
Where the diary has no rows for a metric yet, the value is 0.0 and the label says what is missing.

CLI: python -m oku_slack.world.report --days 7 [--format md|json] [--logs-dir DIR]
"""
import argparse, json, math, os, pathlib, sys
from collections import Counter, defaultdict

DAY = 86400.0
POST_TYPES = ("agent.posted", "porada.requested", "chatter.requested", "podnet.requested", "news.requested")
REAL_LIFE_SOURCES = ("podnet", "news")
CHATTER_SOURCES = ("chatter",)
RESPONSE_WINDOW = 2 * 3600.0  # H1: human response within 2 h of a post
HUMAN_TYPES = ("reaction", "choice.made", "choice.chosen")
COMMIT_TYPES = ("commitment.made", "commitment.created", "slib.made")
INVITE_ACCEPTED = ("wheel.invite.accepted", "invite.accepted")
WHEEL_ROUNDS = ("wheel.live", "wheel.done", "wheel.expired", "wheel.vetoed")
KILL_PREFIX = "kill_switch"
LLM_RATE_NOTE = "est_usd jen z řádků s číselnou cenou"


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0.0


def _payload(r):
    p = r.get("payload")
    return p if isinstance(p, dict) else {}


def _ts(r):
    v = r.get("ts")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else 0.0


def _is_post(r):
    if r.get("type") not in POST_TYPES:
        return False
    return r.get("type") != "agent.posted" or _payload(r).get("top_level", True) is not False


def _has_kill(r):
    if r.get("type") == "world.kill":
        return True
    if r.get("type") != "budget.denied":
        return False
    reasons = _payload(r).get("reasons") or []
    return any(isinstance(x, str) and x.startswith(KILL_PREFIX) for x in reasons)


def _ratio(a, b):
    return round(a / b, 4) if b else 0.0


def build_report(rows, now=None):
    """Pure. Return the readout dict for diary rows (dicts as in logs/world.jsonl)."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if now is None:
        now = max((_ts(r) for r in rows), default=0.0)
    now = float(now)
    start = min((_ts(r) for r in rows), default=now)
    days = int(math.ceil((now - start) / DAY)) if rows and now > start else 0
    period = {"start": float(start), "end": now, "days": days}
    span_days = max(days, 1) if rows else 0

    sources = Counter(str(r.get("source") or "unknown") for r in rows)
    posts = [r for r in rows if _is_post(r)]

    llm_rows = [r for r in rows if r.get("type") == "bridge.reply"]
    llm = {
        "calls": sum(int(_num(_payload(r).get("llm_calls", 1))) for r in llm_rows),
        "est_usd": round(sum(_num(_payload(r).get("est_usd")) for r in llm_rows), 6),
        "fallbacks": sum(1 for r in llm_rows if _payload(r).get("fallback") or _payload(r).get("backend") == "template"),
        "note": LLM_RATE_NOTE,
    }

    # H1: human responses within 2 h per post, grouped by post source (real-life vs chatter)
    reactions = [r for r in rows if r.get("type") in HUMAN_TYPES and r.get("actor")]
    react_by_subj = defaultdict(list)
    for r in reactions:
        if r.get("subject"):
            react_by_subj[r["subject"]].append(_ts(r))

    def responses(post):
        s = post.get("subject")
        t0 = _ts(post)
        return sum(1 for t in react_by_subj.get(s, []) if t0 <= t <= t0 + RESPONSE_WINDOW) if s else 0

    per_src = {}
    for name, srcs in (("real_life", REAL_LIFE_SOURCES), ("chatter", CHATTER_SOURCES)):
        sel = [p for p in posts if p.get("source") in srcs]
        resp = sum(responses(p) for p in sel)
        per_src[name] = {"posts": len(sel), "responses": resp, "per_post": _ratio(resp, len(sel))}
    h1_val = per_src["real_life"]["per_post"]
    h1_label = "lidské reakce do 2 h na post (podnety/zprávy), na post"
    if not per_src["real_life"]["posts"]:
        h1_label += " - zatím žádné podnety/zprávy v deníku"
    h1 = {"metric": h1_label, "value": h1_val, "by_source": per_src,
          "chatter_per_post": per_src["chatter"]["per_post"]}

    # H2: positive-reaction share on posts with memory briefs vs without (polarity: payload.polarity == "positive")
    def is_positive(r):
        return _payload(r).get("polarity") == "positive"

    with_brief = [p for p in posts if _num(_payload(p).get("brief_chars")) > 0]
    without = [p for p in posts if _num(_payload(p).get("brief_chars")) <= 0]

    def pos_share(group):
        subjects = {p.get("subject") for p in group if p.get("subject")}
        rs = [r for r in reactions if r.get("subject") in subjects]
        return _ratio(sum(1 for r in rs if is_positive(r)), len(rs))

    h2_with, h2_without = pos_share(with_brief), pos_share(without)
    h2_label = "podíl pozitivních reakcí: posty s pamětí vs bez paměti (polarity v deníku zatím není -> 0.0)"
    if not any(is_positive(r) for r in reactions):
        h2_label += " - žádná pozitivní reakce v deníku"
    h2 = {"metric": h2_label, "value": h2_with, "without_brief": h2_without,
          "posts_with_brief": len(with_brief), "posts_without_brief": len(without)}

    # H3: negative signals per week (kill/silence rows)
    kills = sum(1 for r in rows if _has_kill(r))
    weeks = (days / 7.0) if days else 0.0
    h3 = {"metric": "negativní signály (kill/ticho) za týden", "value": _ratio(kills, weeks) if weeks else float(kills),
          "count": kills}

    # H4: abundance vs scarcity: posts and non-material actions per day, by regime
    nonmat = [r for r in rows if r.get("type") in HUMAN_TYPES or r.get("type") == "bridge.reply"]
    by_regime = defaultdict(lambda: {"posts": 0, "non_material": 0})
    for p in posts:
        by_regime[str(p.get("regime") or "unknown")]["posts"] += 1
    for r in nonmat:
        by_regime[str(r.get("regime") or "unknown")]["non_material"] += 1
    regimes = {k: {"posts_per_day": _ratio(v["posts"], span_days), "non_material_per_day": _ratio(v["non_material"], span_days),
                   **v} for k, v in sorted(by_regime.items())}
    h4 = {"metric": "neměrné akce za den (reakce, volby, odpovědi); posty za den v posts_per_day",
          "value": _ratio(len(nonmat), span_days), "posts_per_day": _ratio(len(posts), span_days),
          "by_regime": regimes}

    # H5: engagement without currency: active human days and commitments made
    human_days = {int(_ts(r) // DAY) for r in rows if r.get("type") in HUMAN_TYPES and r.get("actor")}
    commits = sum(1 for r in rows if r.get("type") in COMMIT_TYPES)
    h5_label = "aktivní lidské dny (reakce/volby)"
    if not commits:
        h5_label += "; závazky (/oku slib) zatím v deníku nejsou -> 0"
    h5 = {"metric": h5_label, "value": float(len(human_days)), "commitments_made": commits}

    # H6: wheel as bonus: invitations accepted and live rate of rounds (wheel half not yet in the diary)
    accepted = sum(1 for r in rows if r.get("type") in INVITE_ACCEPTED)
    live = sum(1 for r in rows if r.get("type") == "wheel.live")
    rounds = sum(1 for r in rows if r.get("type") in WHEEL_ROUNDS)
    h6_label = "podíl živých kol z uzavřených (pozvánky zatím v deníku nejsou -> 0)" if not accepted else \
        "podíl živých kol z uzavřených; pozvánky přijaté v počtu"
    h6 = {"metric": h6_label, "value": _ratio(live, rounds), "invitations_accepted": accepted, "live_rounds": live,
          "rounds": rounds}

    return {"period": period, "rows": len(rows), "posts": len(posts), "sources": dict(sorted(sources.items())),
            "llm": llm,
            "hypotheses": {"H1": h1, "H2": h2, "H3": h3, "H4": h4, "H5": h5, "H6": h6},
            "channels": _top(rows, lambda r: str(r.get("subject") or "").split(":")[1] if str(r.get("subject") or "").startswith("slack:") else None),
            "personas": _top(rows, lambda r: r.get("actor")),
            }


def _top(rows, pick, n=5):
    c = Counter(v for v in (pick(r) for r in rows if r.get("type") in POST_TYPES + HUMAN_TYPES) if v)
    return [{"name": k, "count": v} for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def report_text(report):
    """Deterministic Markdown readout."""
    p = report["period"]
    lines = [
        "# OKÚ svět: readout (P-008)", "",
        f"- Období: {p['days']} dní (od {p['start']:.0f} do {p['end']:.0f})",
        f"- Řádky deníku: {report['rows']}, autonomní posty: {report['posts']}",
        f"- LLM volání: {report['llm']['calls']}, odhad nákladu: ${report['llm']['est_usd']:.4f}, "
        f"záložní šablony: {report['llm']['fallbacks']} ({report['llm']['note']})", "",
        "## Zdroje", "", "| zdroj | řádky |", "|---|---|",
    ]
    lines += [f"| {s} | {n} |" for s, n in sorted(report["sources"].items(), key=lambda kv: (-kv[1], kv[0]))]
    lines += ["", "## Hypotézy H1-H6", ""]
    for k in ("H1", "H2", "H3", "H4", "H5", "H6"):
        h = report["hypotheses"][k]
        lines.append(f"- **{k}** {h['metric']}: {h['value']}")
    lines += ["", "## Aktivní kanály", ""]
    lines += [f"- {c['name']}: {c['count']}" for c in report["channels"]] or ["- (zatím žádné)"]
    lines += ["", "## Aktivní persony", ""]
    lines += [f"- {c['name']}: {c['count']}" for c in report["personas"]] or ["- (zatím žádné)"]
    return "\n".join(lines) + "\n"


def causal_chain(rows, event_id):
    """The row with event_id plus its ancestors via causal_parents, oldest first. Missing parents are skipped."""
    by_id = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get("id") is not None:
            by_id.setdefault(r["id"], r)
    if event_id not in by_id:
        return []
    seen, stack, out = set(), [event_id], []
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id:
            continue
        seen.add(cur)
        row = by_id[cur]
        out.append(row)
        for par in row.get("causal_parents") or []:
            if isinstance(par, str):
                stack.append(par)
    out.sort(key=lambda r: (_ts(r), str(r.get("id"))))
    return out


def load_rows(logs_dir=None):
    """Diary rows from logs/world.jsonl. Missing file -> []; a half-written line is skipped."""
    base = pathlib.Path(logs_dir or os.environ.get("OKU_WORLD_LOGS") or pathlib.Path(__file__).resolve().parents[2] / "logs")
    path = base / "world.jsonl"
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m oku_slack.world.report", description="OKÚ world readout (P-008)")
    ap.add_argument("--days", type=int, default=7, help="period in days (default 7)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    ap.add_argument("--logs-dir", default=None, help="directory with world.jsonl (default OKU_WORLD_LOGS or <repo>/logs)")
    args = ap.parse_args(argv)
    rows = load_rows(args.logs_dir)
    if rows and args.days > 0:
        end = max(_ts(r) for r in rows)
        rows = [r for r in rows if _ts(r) >= end - args.days * DAY]
    report = build_report(rows)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(report_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
