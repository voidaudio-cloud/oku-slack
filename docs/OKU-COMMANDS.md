# /oku commands (P-002 command layer)

Source: `oku_slack/world/commands.py` (pure, stdlib only). Plan: `docs/ECOSYSTEM-PLAN.md:227-233`.
Replies are ephemeral. Free text from the diary never reaches a reply (`docs/ECOSYSTEM-PLAN.md:255`).

## Commands

| Command | Who | What it answers | Help string (Czech) |
|---|---|---|---|
| `/oku svet` (`/oku svět`, or bare `/oku`) | anyone, ephemeral | Regime, resources, blame and the 7-day numbers from `GET /api/world` | Stav světa OKÚ: režim, zdroje, vina a aktivita za 7 dní (kdokoli, jen pro tebe). |
| `/oku denik [n]` | anyone, ephemeral | Last n diary rows (default 20, max 50) as one-liners: id, type, actor, subject, short reason. No payload text | Posledních n záznamů deníku jako řádky bez obsahu zpráv (výchozí 20, kdokoli). |
| `/oku proc <we_id>` | anyone, ephemeral | Causal chain of one row (ancestors via `causal_parents`, oldest first) with the director's reasons, candidate count and rng key. This is the "every fire is explainable" check (P-005) | Příčinný řetězec jednoho záznamu a důvody režiséra, `/oku proc <id>` (kdokoli). |
| `/oku ticho [h]` | owner | Silence the personas for h hours (P-003, not in this layer yet) | Ztišit postavy na h hodin, `/oku ticho [h]` (jen vlastník, fáze P-003). |
| `/oku nahlas` | owner | Lift the silence (P-003) | Zrušit ticho postav (jen vlastník, fáze P-003). |
| `/oku podnet <url> [postava]` | owner | Manual real-life trigger (P-004) | Ručně přidat podnět z odkazu, `/oku podnet <url> [postava]` (jen vlastník, fáze P-004). |
| `/oku rezim A\|B\|C` | owner | Switch the world regime (P-007) | Přepnout režim světa A, B nebo C (jen vlastník, fáze P-007). |
| `/oku slib <text>` | players | Record a player promise to the personas (P-007) | Zapsat hráčský slib postavám, `/oku slib <text>` (hráči, fáze P-007). |

Commands marked P-003 and later are parsed and listed in help, but `handle()` answers them with a
"přijde v další fázi" line. They are not implemented here.

## Router

- `parse(text)` returns `(command, args)`. The `/oku` prefix is required and case-insensitive. `svět` is an alias of `svet`.
  An unknown or empty input returns `("unknown", [])`.
- `handle(text, fetch=None)` parses, fetches through `fetch(path, query)` and renders. When `fetch` is None it calls the
  loopback world API at `http://127.0.0.1:8798` (override with `OKU_WORLD_URL`), with no proxies and a 2 s timeout.
  It never raises. On any failure it returns a short Czech line.

## Not done here (Kore)

- The dedicated "OKU Svět" Slack app must be created and installed by Kore.
- The `/oku` command registration in that app is also Kore's step.
- The thin Slack adapter that calls `handle()` is not written. `manifests/` and `oku_slack/bridge.py` are untouched.
