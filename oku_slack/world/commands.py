"""`/oku` command layer (P-002, docs/ECOSYSTEM-PLAN.md:227-233): parsing, routing to the world API and rendering the
ephemeral reply text. Pure and stdlib only. The Slack wiring (the dedicated OKU Svět app, the /oku registration and
the bridge) is NOT here; Kore wires a thin adapter on top of `handle()` later.

Privacy rule (docs/ECOSYSTEM-PLAN.md:255): no free text reaches a reply from the diary. `render_denik` and `render_proc`
print metadata only (id, type, actor, subject, decision reasons); payloads that carry message content are shown as
"(obsah vynechán)"."""
import json, os, urllib.parse, urllib.request
from .state import REGIMES, RESOURCES

WORLD_URL = "http://127.0.0.1:8798"
ALIASES = {"svět": "svet"}
COMMANDS = {
    "svet": "Stav světa OKÚ: režim, zdroje, vina a aktivita za 7 dní (kdokoli, jen pro tebe).",
    "denik": "Posledních n záznamů deníku jako řádky bez obsahu zpráv (výchozí 20, kdokoli).",
    "proc": "Příčinný řetězec jednoho záznamu a důvody režiséra, `/oku proc <id>` (kdokoli).",
    "ticho": "Ztišit postavy na h hodin, `/oku ticho [h]` (jen vlastník, fáze P-003).",
    "nahlas": "Zrušit ticho postav (jen vlastník, fáze P-003).",
    "podnet": "Ručně přidat podnět z odkazu, `/oku podnet <url> [postava]` (jen vlastník, fáze P-004).",
    "rezim": "Přepnout režim světa A, B nebo C (jen vlastník, fáze P-007).",
    "slib": "Zapsat hráčský slib postavám, `/oku slib <text>` (hráči, fáze P-007).",
}
PENDING = {"ticho", "nahlas", "podnet", "rezim", "slib"}
# Keys whose value is message content (a reply, a draft, a headline). Never rendered.
CONTENT_KEYS = {"text", "message", "content", "body", "reply", "opener", "turns_text", "draft", "quote", "raw",
                "headline", "lines", "prompt"}
PHRASE_MAX = 80

def parse(text):
    """'/oku <sub> [args]' -> (sub, args). '/oku' alone is the default view ('svet'); anything else is 'unknown'."""
    parts = (text or "").strip().split()
    if not parts or parts[0].lower() != "/oku": return ("unknown", [])
    if len(parts) == 1: return ("svet", [])
    sub = parts[1].lower()
    sub = ALIASES.get(sub, sub)
    if sub not in COMMANDS: return ("unknown", [])
    return (sub, parts[2:])

def _num(n):
    try: return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError): return str(n)

def _cut(s, n=PHRASE_MAX):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"

def _reason(payload):
    """Short metadata reason: the director's `why` checks (never content keys)."""
    why = payload.get("why")
    if isinstance(why, (list, tuple)): return _cut("; ".join(str(x) for x in why[:2]))
    if isinstance(why, str): return _cut(why)
    return "—"

def _has_content(payload):
    return any(k in payload for k in CONTENT_KEYS)

def render_svet(snapshot):
    """World snapshot (GET /api/world) as one Slack-ready message: regime, every resource, blame and the 7-day numbers."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    regime = snap.get("regime")
    lines = [f"🌍 *Stav světa OKÚ* · {REGIMES.get(regime, regime or 'režim neznámý')}"]
    res = snap.get("resources") or {}
    if res:
        parts = []
        for k, v in res.items():
            emo, label = (RESOURCES[k][2], RESOURCES[k][3]) if k in RESOURCES else ("•", k)
            parts.append(f"{emo} {label} {_num(v)}")
        lines.append(" · ".join(parts))
    blame = snap.get("blame") or {}
    rows = [f"{k} {v}" for k, v in sorted(blame.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0][:5]
    lines.append("🫵 Vina: " + (" · ".join(rows) or "zatím nikdo"))
    m = snap.get("metrics_7d") or {}
    if m:
        rate = f"{round(100 * m.get('live', 0) / m['spun'])} %" if m.get("spun") else "—"
        lines.append(f"📊 Za 7 dní: {m.get('spun', 0)}× točeno, {m.get('live', 0)}× živě ({rate}), "
                     f"{m.get('human_actions', 0)} akcí hráčů, {m.get('bridge_calls', 0)} odpovědí postav")
    lines.append("_Svět si pamatuje: události mění zdroje, vinu i vztahy postav._")
    return "\n".join(lines)

def render_denik(rows, limit=20):
    """Last `limit` diary rows as one-liners: id, type, actor, subject, short reason. Never payload text."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    try: limit = max(1, min(50, int(limit)))
    except (TypeError, ValueError): limit = 20
    rows = rows[-limit:]
    if not rows: return "📖 Deník je zatím prázdný."
    out = [f"📖 *Deník světa* · posledních {len(rows)}"]
    for r in rows:
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        note = " · (obsah vynechán)" if _has_content(payload) else ""
        out.append(f"`{r.get('id', '?')}` {r.get('type', '?')} · {_cut(r.get('actor') or '—', 24)} · "
                   f"{_cut(r.get('subject') or '—', 40)} · {_reason(payload)}{note}")
    return "\n".join(out)

def _chain(rows, event_id):
    """Ancestors of event_id via causal_parents, oldest first, the event itself last. Cycle-safe."""
    by_id = {r.get("id"): r for r in rows if isinstance(r, dict) and r.get("id")}
    if event_id not in by_id: return None, []
    seen, stack = set(), [event_id]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id: continue
        seen.add(cur)
        stack.extend(p for p in (by_id[cur].get("causal_parents") or []) if isinstance(p, str))
    seen.discard(event_id)
    ordered = sorted((by_id[i] for i in seen), key=lambda r: (r.get("ts") or 0, r.get("seq") or 0))
    return by_id[event_id], ordered

def render_proc(rows, event_id):
    """Causal chain of one row (ancestors oldest first) with the director's reasons, candidates and rng key."""
    target, ancestors = _chain(rows, event_id)
    if target is None: return f"🔎 Záznam `{event_id}` v deníku nenalezen."
    out = [f"🔎 *Příčinný řetězec* `{event_id}`"]
    for r in ancestors + [target]:
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        mark = "▶" if r is target else "↳"
        line = f"{mark} `{r.get('id', '?')}` {r.get('type', '?')} · {_cut(r.get('subject') or '—', 40)}"
        cands = payload.get("candidates")
        if isinstance(cands, (list, tuple)) and cands: line += f" · kandidáti {len(cands)}"
        if payload.get("rng_key"): line += f" · klíč {_cut(payload['rng_key'], 40)}"
        line += f" · důvod: {_reason(payload)}"
        if _has_content(payload): line += " · (obsah vynechán)"
        out.append(line)
    if not ancestors: out.append("_Bez příčiny: záznam vznikl přímo ze zdroje._")
    return "\n".join(out)

def _http_get(path, query):
    """GET loopback world API, no proxies, short timeout. Returns parsed JSON or None; never raises."""
    base = (os.environ.get("OKU_WORLD_URL") or WORLD_URL).rstrip("/")
    url = base + path + (("?" + urllib.parse.urlencode(query)) if query else "")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2.0) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None

DOWN = "🌍 Svět OKÚ teď neodpovídá (služba oku_world neběží). Zkus to později."

def handle(text, fetch=None):
    """Route one `/oku` line: parse, fetch through `fetch(path, query)` (default: loopback world API), render.
    Never raises; failures come back as a short Czech line."""
    sub, args = parse(text)
    get = fetch or _http_get
    try:
        if sub == "unknown":
            return "Neznámý příkaz. Dostupné: " + " · ".join(f"/oku {k}" for k in COMMANDS) + "."
        if sub in PENDING:
            return f"/oku {sub} přijde v další fázi (zatím jen popis: {COMMANDS[sub]})"
        if sub == "svet":
            snap = get("/api/world", {})
            return render_svet(snap) if isinstance(snap, dict) and snap else DOWN
        if sub == "denik":
            limit = 20
            if args:
                if not args[0].isdigit(): return "Použij: /oku denik [n], kde n je číslo."
                limit = int(args[0])
            data = get("/api/world", {"events": max(1, min(50, limit))})
            if not isinstance(data, dict): return DOWN
            return render_denik(data.get("events") or [], limit)
        if sub == "proc":
            if not args: return "Použij: /oku proc <id záznamu>, např. /oku proc we_0007."
            data = get("/api/world", {"events": 500})
            if not isinstance(data, dict): return DOWN
            return render_proc(data.get("events") or [], args[0])
    except Exception:
        return DOWN
    return DOWN
