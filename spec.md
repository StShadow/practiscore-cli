# PractiScore Squadding API — Reverse Engineering Spec

**Version:** 2.2 (live-verified)
**Target:** `https://practiscore.com`
**Goal:** Python library for programmatic squad management (add / move / remove shooters)
**Discovery match:** slug `test-reverse-engineer`, `matchId=351459`, squads `1458603/1458604/1458605` (3 squads × 5 slots)

Tags: `[V]` verified by live request+response · `[S]` read from client source, not exercised · `[I]` inferred / untested

**v2.2 changes (re-verified 2026-07-26, authenticated admin session):** the four mutating endpoints that v2.1 could only carry forward on prior evidence were **all re-exercised live** against the sandbox and the match was returned to its exact initial layout. Every test below was run through the page's own session (`fetch`, `credentials:'same-origin'`), notifications suppressed throughout.

1. **All four `check` branches re-confirmed** — `added/1`, `same/1`, `taken/2`, `move/1`, and `move/3` (§3.3). `num` semantics pinned: on `taken` it is the **target** slot's squad; on `same`/`move` it is the **shooter's current** squad.
2. **`save` re-confirmed** — bare `moved` (5 bytes, `200`); origin slot auto-vacated; **exact position honored** (committed to Squad 3 *position 3*, not the first free slot) (§3.4).
3. **CSRF unenforced re-confirmed on *both* write paths** — `check` returned `added` and `save` returned `moved` each with the `X-CSRF-TOKEN` header **entirely omitted** (§6.1).
4. **`removeask` admin branch pinned to `ask`** (§3.5) — the authenticated admin session returns `ask` (`200`), vs. `noAuth` for the anonymous caller (v2.1). The self-squad / squad-lead middle of the matrix is still open.
5. **Lock re-confirmed as a non-interlock** — toggle returns `{"success":true}` and flips the button `btn-primary`⇄`btn-danger`; a full `check`→`save` move **completed and persisted while the match was locked** (§3.7).
6. **`removeshooter` re-confirmed** — unsquads the shooter but keeps the match registration (roster stayed at 2), and accepts an **arbitrary position** in its `spot_` info (used it to clean up the overflow test in #7). Network-layer status is ambiguous — see §3.6.
7. **NEW — squad capacity / position range is NOT server-enforced** (§3.3, §6.8, resolves §7.4). `check` **added** a shooter to **position 7** of a 5-slot squad, returning `{"cmd":"added","num":1}`. The shooter became a **hidden assignment**: the squadding page (which renders only positions 1–5) showed the squad empty, while a follow-up `check` returned `same`, proving the record exists. This is a second data-integrity hazard on par with the `save` double-assignment (§3.4).

**v2.1 changes (re-verified 2026-07-25, unauthenticated):** four read-path findings, all reproduced with **no session cookie at all**. Retained below; still valid.

**v2.0 changes:** all four `check` branches exercised live; `save`, `removeask`, `removeshooter`, and `lock` response shapes captured; CSRF found to be unenforced; `save` found to be unvalidated and capable of corrupting state; `LIKE` wildcards confirmed; lock found not to block API writes.

**v2.1 changes (re-verified 2026-07-25, unauthenticated):** four findings that materially change the threat model and the response-handling contract, all reproduced with **no session cookie at all** (only Cloudflare-issued cookies present):

1. **`GET /squads/registered` requires NO authentication.** A cookieless, header-less request returns the full roster *including every shooter's email address* (§3.2, §6.6). The auth boundary is narrower than v2.0 assumed: only the bootstrap HTML page (§3.1) is gated — it 302-redirects to `/login`. Search and `removeask` are open.
2. **`removeask == "noAuth"` is now `[V]`, not `[S]`** (§3.5). An unauthenticated request returns the bare string `noAuth` (`200`, `text/html`). This resolves the "highest remaining priority" open question §7.1 for the *anonymous* case; the full admin/squad-lead/self-squad permission matrix is still open.
3. **The "always `text/html`" rule is false** (§3, §3.2). Search results, its `404`/`500` errors, and `check`'s `500` all return `Content-Type: application/json`; only `removeask` returned `text/html`. Content-type is genuinely mixed — the "never branch on content-type, try `json.loads` then fall back to bare-string" contract is *still correct* and is why it survives this change.
4. All §3.2 `LIKE`/scoping rows and the roster payload re-confirmed byte-for-byte (ids `9808574`/`9808577`, trailing whitespace on both names, `shDiv` Production/Standard).

The four **mutating** endpoints (`check` add-path, `save`, `removeshooter`, `lock`) could **not** be re-exercised on 2026-07-25 — they sit behind the login gate and no authenticated session was available. ~~Their v2.0 `[V]` tags stand on the prior session's evidence; treat them as un-re-verified as of this date.~~ **Superseded by v2.2 (2026-07-26): all four were re-exercised live under an authenticated admin session and their `[V]` tags now stand on current evidence — see the v2.2 changelog above and §8.2.**

---

## 0. Product requirements (v1)

Captured with the product owner, 2026-07-26. This section is the source of truth for *what to build*; §1–§8 document the underlying API that constrains *how*.

### 0.1 Scope

A **CLI tool** (shipped as a Python **script/repo** for v1 — no PyPI package or standalone `.exe` yet) that manipulates squads for **one match at a time**. Built on a reusable library core (§5).

**Match selection.** The user identifies the target match by its **URL slug** (e.g. `test-reverse-engineer`, from `practiscore.com/{slug}/squadding`) or by pasting the full squadding URL. Given the slug, the tool loads the bootstrap page (§3.1) and **auto-discovers** the internal `matchId` and all squads. The slug can be saved as a **default in a local config file** so it need not be retyped; an explicit `--match <slug|url>` overrides the default. There is **no `list matches` picker in v1** (see §0.4).

### 0.2 Functional requirements

| # | Requirement | Notes / API mapping |
|---|---|---|
| F0 | **Select the target match** by slug/URL, with an optional saved default | `--match <slug\|url>` or config default; tool scrapes the bootstrap page (§3.1) to derive `matchId` + squads. No `list matches` picker in v1 (§0.4). |
| F1 | **List all squads** | Displayed squad number + occupancy/free counts. Squads addressed by **displayed number** (Squad 1, 2, 3…), mapped internally to `squadId` — the two differ and numbers are not guaranteed ordered/contiguous (§2.1). |
| F2 | **List shooters** — full roster as `(name, ID)` tuples | ID is the match registration ID used by every other call (§2.3). Also **list shooters within a given squad**. |
| F3 | **Move one shooter to another squad** | `move <shooterID> <squadNumber>`. Implemented as `check`→`save` (§4). |
| F4 | **Move a list of shooters to a target squad** (bulk) | Same target squad for the batch; continue-and-report on partial failure (NF5). |
| — | Shooters are referenced **by ID**; squads **by displayed number**. | Names are display/discovery only (messy: non-ASCII, trailing spaces, possible duplicates — §0.4). |

### 0.3 Non-functional requirements

| # | Area | Requirement |
|---|---|---|
| NF1 | **Authentication** | Paste a browser **session cookie** (no API keys exist; §1). Ship a **how-to guide for grabbing the cookie in Firefox and Chrome**, including how to re-grab when it expires. The library accepts a pre-authenticated session; it does **not** implement login (Turnstile-gated, §5). |
| NF2 | **Session expiry mid-run** | On auth failure during a long run, **pause and wait**: prompt the user to paste a fresh cookie, then **resume from the checkpoint** (see NF6). |
| NF3 | **Output** | Human-friendly **tables by default**; **`--json`** flag for machine-readable output on every read command. |
| NF4 | **Notifications** | **Silent by default** (`email=0` / `send=no`, §3.3/§3.4). Sending is opt-in via **`--notify`**. |
| NF5 | **Mutation safety** | **Dry-run preview + confirm** before any write ("will move Anatoli: Squad 2 → Squad 3"); **`--yes`** skips the prompt for scripting. **Bulk partial failure = continue-and-report**: move everyone who can be moved, then report each failure with its reason (`taken`, already-present, etc.). No transactional rollback (the API has none). |
| NF6 | **Scale, pacing & resumability** | Target size up to **~300 shooters / ~30 squads**. Pace requests at **near-human speed with jitter + backoff** (Cloudflare Turnstile + rate limits, §5); a full run may take **10–20 min** and shows a **live progress bar**. Runs are **checkpointed and resumable** — an interrupted run continues where it left off rather than restarting. |
| NF7 | **Exclusivity via lock** | Before mutating, **read lock state; if unlocked, lock it** (toggle semantics, §3.7). **Leave it locked** at the end and print a clear **lock-status line**. ⚠️ Documented limitation surfaced to the user: **lock only blocks public/self-service squadding, not other admins or the API itself** (§3.7) — exclusivity holds against shooters, not against a second admin. |
| NF8 | **Audit log** | Write a **local audit log** of every move (`timestamp, shooter, from-squad → to-squad, outcome`). **Emails may be included** per the owner's explicit choice (private, single-user use). Keep the file **local** — not committed to git, not shared. |
| NF9 | **Privacy of PII** | Shooter **emails are never written to normal output/logs** (§3.2/§6.6); they appear **only** in the NF8 audit file. |
| NF10 | **Correctness under API sharp edges** *(assumed, owner-accepted)* | Always `check` a slot before `save`; **never `save` unless the preceding `check` returned `move`** (§3.4); **never write to an occupied or out-of-range slot** (guards the hidden double-assignment §3.4 and out-of-range hidden-assignment §3.3/§6.8 hazards); **re-read to confirm** post-conditions. |
| NF11 | **Encoding** *(assumed, owner-accepted)* | Correctly handle **UTF-8 names** (Cyrillic, Polish diacritics) and **trailing whitespace** (§3.2), including in the **Windows terminal**. |

### 0.4 Explicitly out of scope for v1

Squad create/delete; standalone `.exe` / PyPI packaging; **a `list matches` dashboard picker** (requires reverse-engineering a separate account/matches endpoint — deferred; v1 selects a match by slug/URL per §0.1); multi-match operations in one invocation; automated login; notification-path behavior beyond the opt-in flag; the squad-lead/self-squad permission middle-ground (§7.1).

---

## 1. Architecture summary

Server-rendered Laravel + jQuery. No REST API, no versioning, no API tokens.

1. **Auth = Laravel session cookie.** No API key mechanism exists. `[V]`
2. **CSRF is scraped but *not enforced* on the squadding write endpoints.** The page sends `X-CSRF-TOKEN` via `$.ajaxSetup`, but `check` and `save` both succeed with the header omitted entirely. See §6. `[V]`
3. **Resources are addressed by DOM element IDs.** The composite string `squad_{squadId}_{position}_{matchId}` is passed verbatim as a URL path segment. A client must scrape the page to build its address space. `[V]`
4. **Responses are inconsistent**: JSON objects, JSON arrays, bare strings, and 302 redirects — all served as `Content-Type: text/html`. Never branch on content-type. `[V]`

---

## 2. Identifier model

### 2.1 Slot identifier

Each squad position is an `<input>`:

```
id  = squad_{squadId}_{position}_{matchId}      e.g. squad_1458603_1_351459
rel = {squadNumber}                              e.g. "1"
```

| Component | Meaning | Example |
|---|---|---|
| `squadId` | Opaque internal squad PK | `1458603` |
| `position` | 1-based slot index within squad | `1`..`5` |
| `matchId` | Internal match PK | `351459` |
| `rel` | Displayed squad number | `1` |

`squadId` is **not** the squad number. Observed `1458603→Squad 1`, `1458604→Squad 2`, `1458605→Squad 3`; contiguous here but **must not be assumed** contiguous or ordered. `[V]`

**Position is honored exactly.** Committing a move to `squad_1458605_3_351459` placed the shooter in squad 3 position 3, not the first free slot. `[V]`

### 2.2 Prefix variants — critical gotcha

The same slot takes **three different prefixes** by endpoint:

| Prefix | Endpoint | Example |
|---|---|---|
| `squad_` | `check`, `save`, `registered` (path segment) | `squad_1458603_1_351459` |
| `spot_` | `removeshooter` → `info` param | `spot_1458603_1_351459` |
| `clearSpot_` | `removeask` → `info` param | `clearSpot_1458603_1_351459` |

`[V]` for `squad_` and `clearSpot_`; `[S]` for `spot_` (read from rendered form; the removal itself was exercised and returned a redirect).

Store one canonical `(squad_id, position, match_id)` tuple and render the prefix per endpoint.

### 2.3 Shooter identifier

`shooterId` is the shooter's **match registration ID**, returned as `id` by the search endpoint. Observed `9808574`, `9808577`. Not a global user ID. `[I]`

Registration and squadding are **separate**: removing a shooter from a squad leaves them on the match roster, still returned by search. `[V]`

### 2.4 Page identifiers

| Selector | Meaning |
|---|---|
| `meta[name="csrf-token"]` | Token for AJAX header `[V]` |
| `input[name="_token"]` | Token for form posts `[V]` |
| `div#toggle_schedule_{scheduleId}.squadding` | Schedule/day container; observed `340383` `[V]` |
| `strong#squadBox_{squadId}` | Squad header text (`"Squad 1"`) `[V]` |
| `div.squadBox` | Per-squad wrapper `[V]` |
| `span#clearSpot_{...}` | "clear slot" click target `[V]` |
| `div#delModal_{...}` | Per-slot delete modal containing removal form `[V]` |
| slot `value` | Occupant display name; empty ⇒ slot free `[V]` |
| slot `data-original-title` | `"Name (Division)"` or `"Name (Division / Class)"` `[V]` |
| slot `placeholder="reserved"` | **Reserved** slot (UI tints `#f2dede`) `[S]` |
| slot `disabled` | **Disabled** slot (UI tints `#f2dede`); free slots tint `#dff0d8` `[S]` |
| `button#lockSquadding` | Lock toggle; `.btn-primary`+"Lock Squadding" ⇒ currently unlocked, `.btn-danger`+"Unlock Squadding" ⇒ locked `[V]` |

Reserved/disabled slots were **not present** in the discovery match — a client should skip slots with `disabled` or `placeholder="reserved"` when auto-selecting. Server-side enforcement is `[I]`.

Multi-day matches group squads under `toggle_schedule_{scheduleId}`. Only single-schedule observed; multi-schedule is `[I]`.

---

## 3. Endpoint reference

~~All responses carry `Content-Type: text/html` regardless of actual body format.~~ **Corrected v2.1:** content-type is **mixed and unreliable**. `GET /squads/registered` (results + its `404`/`500`) and `check`'s `500` return `application/json`; `removeask` returns `text/html`. The v2.0 rule held for the endpoints then exercised but does not generalize. **Still: never branch on content-type — parse the body directly** (`json.loads`, fall back to bare-string). `[V]`

### 3.1 `GET /{matchSlug}/squadding` — bootstrap

Full HTML page. **Only discovery mechanism found**; there is no JSON listing endpoint. `[V]`

Parse: CSRF token, `matchId`, all `input[id^="squad_"]` with `rel`, `value`, `data-original-title`, `disabled`, `placeholder`; squad names from `strong#squadBox_*`; lock state from `button#lockSquadding`.

Page self-reloads every 120 s, capped at 5 reloads via `sessionStorage.squadRefreshCount` — confirming **concurrent external mutation is expected**. `[V]`

### 3.2 `GET /squads/registered/{slotId}/{query}` — shooter search

`slotId` uses `squad_` prefix. `query` is URL-encoded into the path (client substitutes into `/squads/registered/HOLDERID/%QUERY%`).

> **⚠️ Unauthenticated (re-verified 2026-07-25).** This endpoint needs **no session cookie and no `X-Requested-With` header** — an anonymous request returns the full roster with email addresses. Do not assume the caller is authenticated here; a client must not rely on this route to test session validity. See §6.6.

**Response** `200`, **`Content-Type: application/json`** (not `text/html` — see §3 correction), JSON array:

```json
[{"id":9808574,"name":"Grzegorz Brzęczyszczykiewicz ","email":"...","shDiv":"Production","shClass":""}]
```

| Field | Notes |
|---|---|
| `id` | shooterId for all other calls |
| `name` | display name — **may have trailing whitespace**, strip it `[V]` |
| `email` | **PII — never log or persist** |
| `shDiv` | division; `""` or null when unset |
| `shClass` | class; `""` or null when unset |

**Scoping:** only the `matchId` inside `slotId` matters. `squadId` and `position` are ignored — a valid squad slot, a slot from a different squad, and even `position=99` all returned the identical full roster. A wrong `matchId` or malformed slot → `500`. So a client may reuse **one** arbitrary valid slot ID for all searches. `[V]`

**Query semantics — unescaped SQL `LIKE`** `[V]`:

| Query | Matches | Interpretation |
|---|---|---|
| `a` | 1 of 2 | substring |
| `%20` (space) | 2 of 2 | **effective "list all"** (matches "First Last") |
| `_` | 2 of 2 | wildcard |
| `%25` (`%`) | 2 of 2 | wildcard |
| `An_toli` | 1 → Anatoli | `_` = **single-char** wildcard |
| `An%li` | 1 → Anatoli | `%` = **multi-char** wildcard |
| `zzzq` | 0, `[]` | genuine no-match returns empty array |
| *(empty)* | `404` (`application/json`) | route requires the segment |

All rows above re-verified live 2026-07-25 (`An_toli`→Anatoli, `An%li`→Anatoli, `_`/`%25`→2, `a`→1, `%20`→2, `zzzq`→`[]`). A wrong `matchId` or malformed slot → `500 {"message":"Server Error"}` (`application/json`), also re-confirmed. `[V]`

Clients **must escape `%` and `_`** for literal-name search. Use `%20` for full-roster retrieval. Results include already-squadded shooters. `[V]`

### 3.3 `POST /squads/check/{slotId}/{shooterId}` — add / probe **(MUTATING)**

**The name is misleading — this endpoint performs the add.** `[V]`

```
Content-Type: application/x-www-form-urlencoded
X-CSRF-TOKEN: {token}          # accepted but NOT enforced (§6)
X-Requested-With: XMLHttpRequest

email=0
```

`email` controls the add notification (`0` = suppress). `email=1` not tested — would email a real shooter. `[I]`

**Response** `200`, JSON `{"cmd": <string>, "num": <int>}` — exactly these two keys in all branches. `[V]`

| `cmd` | `num` | Meaning | Mutates? | Correct action |
|---|---|---|---|---|
| `added` | destination squad no. | Shooter placed in the slot | **YES** | Done |
| `taken` | slot's squad no. | Target slot already occupied | No | Choose another slot / reload |
| `same` | shooter's squad no. | Shooter already in this squad | No | No-op |
| `move` | **shooter's *current* squad no.** | Shooter squadded elsewhere | No | `POST /squads/save` to commit |

All four verified live: `{"cmd":"added","num":1}`, `{"cmd":"taken","num":1}`, `{"cmd":"same","num":1}`, `{"cmd":"move","num":1}` / `num:2` / `num:3` — confirming `num` on `move` is the **origin** squad. `[V]`

**Evaluation order:** the same-squad test short-circuits *before* position validation — `position=99` with a shooter already in that squad returned `same` rather than an error. `[V]`

**Position range is never validated — not even on the `added` path (re-verified 2026-07-26).** Adding an *unsquadded* shooter to `squad_1458603_7_351459` — position 7 of a squad that renders only 5 slots — returned `{"cmd":"added","num":1}` and **committed** the assignment. Because the squadding page renders only positions 1–5, the shooter became a **hidden assignment**: the squad appeared empty in the UI while a follow-up `check` returned `same`, confirming the record. The "5 slots" is a UI-rendering limit, **not** a server-side capacity constraint; there is **no distinct "squad full" error** — a slot is only ever `taken` individually, and squads can be silently overflowed into out-of-range positions. Cleanup requires targeting the exact position via `removeshooter` (`spot_..._7_...`), which succeeds. Do not rely on the server to reject out-of-range positions, and always render into a slot you scraped from the page. `[V]` See §6.8.

**Errors** (with `X-Requested-With`): `500` + `{"message":"Server Error"}` for unknown `shooterId`, wrong `matchId` in `slotId`, or a malformed slot ID. No validation error type is distinguishable from the body. `[V]`

### 3.4 `POST /squads/save/{slotId}/{shooterId}` — commit move **(MUTATING, UNVALIDATED)**

```
send=no        # or send=yes to email the shooter
```

**Response** `200`, **bare string** `moved` (5 bytes) — *not* JSON. `[V]`

`send=yes` not tested (would email a real shooter). `[I]`

> ### ⚠️ This endpoint performs no validation whatsoever
>
> `save` is **not** merely a confirmation step. It executes unconditionally:
>
> - It works **without any preceding `check`** — a direct `save` moved a shooter with no probe. `[V]`
> - It works **with no CSRF token**. `[V]`
> - It **ignores slot occupancy**. Saving shooter B onto a slot occupied by shooter A returned `moved` and produced a **hidden double-assignment**: the squadding page rendered only A, while B silently vanished from the UI. A follow-up `check` for B returned `{"cmd":"move","num":1}`, proving B was still recorded in A's squad. `[V]`
>
> **Client requirement:** always call `check` first and only call `save` when `cmd == "move"`. Never expose a raw `save`. Treat an occupied target as a hard client-side error. This is the single largest data-integrity hazard in the API — the UI's own warning ("If a name does not disappear in the old squad after moving the shooter, reload this page") hints the developers know the state can desync.

A successful move **auto-vacates the origin slot**; no explicit clear is needed. `[V]`

### 3.5 `GET /squads/removeask?info=clearSpot_{squadId}_{position}_{matchId}` — permission pre-check

**Response** `200`, `text/html`, **bare string**: `ask` (3 bytes) = authorized. **Re-verified 2026-07-26: the authenticated *admin* session returns exactly `ask` (`200`)** — pinning the admin end of the matrix against the anonymous `noAuth` end. `[V]`
`noAuth` (6 bytes) = caller lacks permission. **`[V]` as of 2026-07-25** — an unauthenticated request returns exactly `noAuth` (`200`, `text/html`, no redirect). The route is **not** login-gated: it evaluates permission and reports the result rather than 302-ing to `/login`. The *admin/squad-lead* branches that yield `ask` remain from the prior authenticated session.

Cheap capability probe for library init. Because it answers for anonymous callers too, `noAuth` is a reliable "this session cannot remove" signal — but a client must not infer general session validity from it (an expired session and a valid-but-unprivileged session both read `noAuth`).

### 3.6 `POST /squads/removeshooter` — remove from squad **(MUTATING)**

Conventional form post, not AJAX.

```
_token = {csrf}
info   = spot_{squadId}_{position}_{matchId}      # note: spot_ prefix
page   = https://practiscore.com/{matchSlug}/squadding
```

**Response:** `3xx` redirect to `page`. Under `fetch` with `redirect:'manual'` the browser masks it as an **opaque redirect** (`type:"opaqueredirect"`, `status:0`) — the status code and `Location` are not readable this way. A concurrent CDP network capture reported `statusCode:503` for the same request, which is **inconsistent** with the opaque-redirect (a `3xx`) that `fetch` observed and with the fact that the mutation **succeeded** every time; treat the `503` as a monitoring/Cloudflare artifact, not the app's real status. **The exact status/`Location` remains best determined server-side** (§7.6): in `requests`, use `allow_redirects=False` and treat any `3xx` as success, then verify the post-condition by re-reading the page. `[V]` (success), `[I]` (exact code).

**Semantics (re-verified 2026-07-26):** unsquads the shooter but **keeps their match registration** — after removal the roster still returned both shooter IDs (n stayed 2) and the slot rendered empty. Accepts an **arbitrary position** in `info` (used `spot_..._7_...` to remove the §3.3 hidden-overflow assignment; it succeeded). `[V]`

`page` is a caller-supplied redirect target; treat as a potential open redirect and always set it yourself rather than echoing server input. `[I]`

### 3.7 `POST /matches/{matchSlug}/lock` — lock/unlock squadding toggle

```
matchId={matchId}
```

**Response** `200`, `{"success": true}`. `[V]`

**Pure toggle** — the identical request both locks and unlocks; the client only tracks state via button class/text. There is no way to *set* a desired state idempotently, so **always read current state from `button#lockSquadding` before toggling**. `[V]`

> ### ⚠️ Locking does NOT block API writes
> With the match locked, a full `check`→`save` move completed successfully (`{"cmd":"move"}` then `moved`) and the change persisted. Slot inputs were not `disabled` for an admin session. The lock appears to gate *public/self-service* squadding only. **Do not treat lock as a safety interlock.** `[V]`

---

## 4. Client behavior contract

```
add(shooter, squad, position):
    slot = resolve(squad, position)            # must be free, not reserved/disabled
    r = POST /squads/check/{squad_(slot)}/{shooter}   body: email=0
    match r.cmd:
        "added" -> success(destination=r.num)
        "taken" -> SlotTakenError(r.num)              # refresh & retry elsewhere
        "same"  -> AlreadyInSquadError(r.num)         # idempotent no-op
        "move"  -> MoveRequiresConfirmationError(origin=r.num)

move(shooter, squad, position, notify=False):
    slot = resolve(squad, position)
    r = POST /squads/check/{squad_(slot)}/{shooter}   body: email=0
    if r.cmd == "added": return success        # wasn't squadded; check already placed them
    if r.cmd == "same":  return no_op
    if r.cmd == "taken": raise SlotTakenError
    if r.cmd == "move":
        b = POST /squads/save/{squad_(slot)}/{shooter}  body: send=(yes|no)
        assert b.strip() == "moved"
        return success                          # origin slot auto-vacated

remove(squad, position):
    slot = resolve(squad, position)
    if GET /squads/removeask?info={clearSpot_(slot)} != "ask": raise NotAuthorizedError
    POST /squads/removeshooter {_token, info=spot_(slot), page=...}   # expect 302
```

**Invariants a correct client must maintain**

1. Never call `save` unless the immediately preceding `check` returned `move` (§3.4).
2. Never call `save` against a slot whose `value` is non-empty.
3. `refresh()` before any batch; occupancy changes underneath you.
4. Treat `taken` as ordinary control flow in bulk operations, not an exception.
5. Verify post-conditions by re-reading the page — the API's own UI warns about desync.
6. **Never fabricate a slot address.** Only ever `check`/`save` into a `(squad_id, position)` scraped from the current page — the server does **not** validate `position` and will silently commit an out-of-range add as a hidden assignment (§3.3/§6.8). Reject any caller-supplied `position` not present in the scraped slot set with `SlotNotFoundError`.

---

## 5. Proposed Python surface

Two layers. The **library core** (`SquadClient`) is a thin, session-based wrapper over the API (§3) with no I/O policy of its own. The **CLI layer** (`practiscore_squads.cli`) owns everything the product requirements (§0) add on top: config/match selection, dry-run+confirm, progress + resumable checkpoints, audit logging, lock orchestration, and `--json` formatting. Keeping them separate means the hazards (§3.4/§6.8) are enforced once in the core and the CLI stays declarative.

### 5.1 Data model

```python
@dataclass(frozen=True)
class Slot:
    squad_id: int
    position: int
    match_id: int
    squad_no: int                    # DISPLAYED squad number (F1/F3 address by this), != squad_id
    occupant: str | None
    reserved: bool = False
    disabled: bool = False

    @property
    def free(self) -> bool:
        return self.occupant is None and not self.reserved and not self.disabled

    def as_squad(self) -> str: return f"squad_{self.squad_id}_{self.position}_{self.match_id}"
    def as_spot(self)  -> str: return f"spot_{self.squad_id}_{self.position}_{self.match_id}"
    def as_clear(self) -> str: return f"clearSpot_{self.squad_id}_{self.position}_{self.match_id}"

@dataclass(frozen=True)
class Shooter:
    id: int
    name: str                        # .strip() applied (§3.2 trailing whitespace)
    email: str                       # PII — see NF9: excluded from __repr__/str and all normal output
    division: str | None
    klass: str | None
    def __repr__(self) -> str:       # never leak email via logging/repr
        return f"Shooter(id={self.id}, name={self.name!r})"

class Cmd(str, Enum):
    ADDED = "added"; TAKEN = "taken"; SAME = "same"; MOVE = "move"

@dataclass(frozen=True)
class MoveOutcome:                    # one bulk-item result (NF5 continue-and-report)
    shooter_id: int
    ok: bool
    from_squad: int | None           # origin squad number, if known
    to_squad: int | None
    detail: str                      # "added" | "moved" | "already there" | "taken" | error msg
    error: Exception | None = None
```

### 5.2 Library core — `SquadClient`

```python
class SquadClient:
    # --- construction / auth (NF1) ---
    def __init__(self, session: requests.Session, match: str): ...   # match = slug OR full squadding URL
    @classmethod
    def from_cookie(cls, cookie: str, match: str) -> "SquadClient": ...
        # build a requests.Session from a pasted Cookie header; library never logs in (§5 Auth)

    # --- discovery (F0/F1/F2) ---
    def refresh(self) -> None: ...                     # (re)scrape bootstrap: match_id, squads, CSRF, lock
    @property
    def match_id(self) -> int: ...                     # auto-discovered from the page (F0)
    def squads(self) -> dict[int, list[Slot]]: ...     # keyed by displayed squad_no
    def free_slots(self, squad_no: int | None = None) -> list[Slot]: ...
    def squad_members(self, squad_no: int) -> list[Shooter]: ...   # F2 (shooters in one squad)
    def roster(self) -> list[Shooter]: ...             # F2 full roster; search("%20")
    def search(self, q: str, literal: bool = True) -> list[Shooter]: ...
    def is_locked(self) -> bool: ...

    # --- single mutation (F3) ---
    # move by shooter ID to a DISPLAYED squad number; position auto-picked (first free) unless given.
    # Enforces NF10: check-before-save, refuses occupied/out-of-range targets, verifies post-state.
    def move(self, shooter_id: int, squad_no: int,
             position: int | None = None, notify: bool = False) -> MoveOutcome: ...
    def add(self, shooter_id: int, squad_no: int,
            position: int | None = None, notify: bool = False) -> MoveOutcome: ...

    # --- bulk (F4, NF5/NF6) ---
    def move_many(self, shooter_ids: list[int], squad_no: int, *,
                  notify: bool = False,
                  on_progress: Callable[[MoveOutcome, int, int], None] | None = None,
                  skip: set[int] | None = None) -> list[MoveOutcome]: ...
        # continue-and-report: never raises for a per-item failure — records it in the returned list.
        # `on_progress(outcome, done, total)` drives the CLI progress bar; `skip` = already-done IDs
        # from a resume checkpoint. Applies pacing (NF6) between requests internally.

    # --- lock orchestration (NF7) ---
    def toggle_lock(self) -> bool: ...                 # returns new state; NOT idempotent — read first
    def ensure_locked(self) -> bool: ...               # lock iff currently unlocked; returns True if it locked

    # --- removal (kept from API map; not a v1 CLI command) ---
    def can_remove(self) -> bool: ...                  # removeask == "ask"
    def remove(self, squad_no: int, position: int) -> None: ...
```

Notes:
- **`squad_no` is always the displayed number** (F0/§0.3); the core maps it to `squad_id` internally, tolerating non-contiguous/unordered numbering (§2.1).
- `move`/`add` return a `MoveOutcome` rather than raising for control-flow cases (`taken`, `same`) so the same objects flow through both single and bulk paths; hard faults (`AuthError`, `ServerError`) still raise.
- The core is **synchronous and stateless between calls** except for the scraped snapshot from `refresh()`; the CLI owns retry/resume/pacing *policy* but the pacing *mechanism* lives in the core so no caller can accidentally hammer the API.

### 5.3 CLI surface (maps §0 requirements)

```
practiscore-squads [GLOBAL] <command> [ARGS]

GLOBAL
  --match <slug|url>     target match; overrides saved default (F0)
  --cookie <value|@file> session cookie; or read from config/env (NF1)
  --json                 machine-readable output instead of tables (NF3)
  --yes                  skip the dry-run confirmation prompt (NF5)
  --notify               send PractiScore emails for moves (default: silent) (NF4)

COMMANDS
  config set-default --match <slug>        save default match to local config (F0)
  squads                                   list all squads + occupancy (F1)
  shooters [--squad N]                     list roster as (name, ID); --squad limits to one squad (F2)
  move <shooterID> --to <squadNumber>      single move (F3)
  move-bulk --to <squadNumber> \
            (--ids a,b,c | --ids-file f)   bulk move; continue-and-report (F4/NF5)
```

CLI behaviors layered on the core:
- **Match selection (F0):** resolve `--match` → config default → error. Slug or full URL accepted.
- **Dry-run + confirm (NF5):** every mutating command first prints the planned actions ("`#123 → Squad 3 (from Squad 2)`") and waits for confirmation; `--yes` bypasses. `--json` on a dry-run emits the plan without executing.
- **Progress + resume (NF6):** `move-bulk` renders a progress bar via `on_progress`, and writes a **checkpoint file** (`.psq-checkpoint-<match>.json`, completed shooter IDs + target). On re-run of the same batch it loads the checkpoint and passes `skip=` so finished moves aren't repeated. Checkpoint is deleted on clean completion.
- **Session expiry (NF2):** on `AuthError` mid-run, **pause**, prompt for a fresh cookie, rebuild the session, and continue from the checkpoint — do not lose progress.
- **Lock (NF7):** before any mutation, call `ensure_locked()`; at the end always print a lock-status line (e.g. `Lock: LOCKED (locked by this run)`), and **never auto-unlock**.
- **Audit (NF8):** append every attempted move to a local audit log (`timestamp, shooter_id, name, email, from→to, outcome`) — **emails included by owner's choice**; file kept local (NF9). Distinct from the resume checkpoint.
- **Privacy (NF9):** table/`--json` output for `shooters` shows `(name, ID)` and division/class but **omits email**; email appears only in the audit file.
- **Encoding (NF11):** force UTF-8 I/O; render non-ASCII names correctly on the Windows console.

### 5.4 Error model

```
SquaddingError
├── AuthError                        # no/invalid session on a gated route
│   └── SessionExpiredError          # was authed, now 302→/login mid-run → CLI pause-and-resume (NF2)
├── NotAuthorizedError               # removeask == "noAuth" (unprivileged session)
├── SlotTakenError(num)              # cmd == "taken"            } surfaced as MoveOutcome(ok=False)
├── AlreadyInSquadError(num)         # cmd == "same"             } in bulk, not raised (NF5)
├── MoveRequiresConfirmationError    # cmd == "move" and confirm disabled
├── SlotNotFoundError                # squad_no/position not present in scraped slots (also guards
│                                    #   caller-supplied out-of-range positions — §3.3/§6.8, NF10)
├── SlotUnavailableError             # reserved or disabled slot
├── ServerError                      # 500 {"message":"Server Error"}
└── UnexpectedResponseError          # save != "moved", etc.
```

### 5.5 Implementation requirements

**Parsing.** `lxml`/`bs4`; slot regex `^squad_(\d+)_(\d+)_(\d+)$`. `.strip()` all names.

**Response handling.** Never trust `Content-Type` — it is mixed (`application/json` for search + its errors + `check`'s `500`; `text/html` for `removeask` **and for `check` success**, §3/§8.2), so branching on it is unsafe. Try `json.loads`, fall back to bare-string comparison. Assert `save` returns exactly `moved` and raise `UnexpectedResponseError` otherwise — a silent non-`moved` body may indicate the unvalidated path did something unintended.

**Auth from cookie (NF1).** `from_cookie()` accepts a pasted `Cookie` header (or `@file`), attaches it to a `requests.Session`, and sets a browser-like `User-Agent`. The library **never logs in** (Turnstile-gated, §7 open Q9). Detect a session that has gone stale by the bootstrap `302→/login` and raise `SessionExpiredError` (NF2). Never persist or log the `email` field or the cookie value.

**CSRF.** Scrape `meta[name="csrf-token"]` on every `refresh()`; send as `X-CSRF-TOKEN` and as `_token` for `removeshooter`. Send it even though it is unenforced (§6.1, re-verified 2026-07-26) — enforcement may be added later. Handle `419` by re-`refresh()` + one retry.

**Headers.** Send `X-Requested-With: XMLHttpRequest` — it changes error bodies from HTML pages to `{"message":"Server Error"}`, which is far easier to handle.

**Move safety (NF10).** `move()` must: `refresh()` (or use a fresh-enough snapshot) → resolve `squad_no`→`squad_id` and pick a **free, scraped** slot → `check` → act only on the returned `cmd` (`added`⇒done, `same`⇒no-op, `taken`⇒`MoveOutcome(ok=False)`, `move`⇒`save`) → **never `save` unless `check` returned `move`** → re-read to confirm. Refuse any target slot whose `value` is non-empty or whose position wasn't scraped (guards §3.4 double-assignment and §3.3/§6.8 out-of-range hidden assignment).

**Search escaping.** Escape `%`→`\%` and `_`→`\_` when `literal=True`; expose `literal=False` for deliberate wildcards. Use `%20` for full-roster retrieval.

**Concurrency.** State mutates externally (UI polls at 120 s). `refresh()` before batches; re-verify after writes; on `taken` in a bulk run, optionally optimistic-retry onto the next free slot of the target squad before recording failure.

**Rate limiting & pacing (NF6).** Cloudflare Turnstile is present site-wide. Pace requests near-human with jitter and exponential backoff; the pacing mechanism lives in the core so bulk runs (≤300 shooters, 10–20 min) cannot accidentally burst.

**Resumability (NF6).** Bulk runs checkpoint completed shooter IDs to a local file keyed by match; resume loads it and passes `skip=`. Checkpoint ≠ audit log; delete checkpoint on clean finish, keep the audit log.

**Notifications (NF4).** Default `notify=False` (`email=0` / `send=no`) so bulk operations never spam shooters. `notify=True` is an explicit opt-in (`--notify`).

**Lock (NF7).** `ensure_locked()`/`toggle_lock()` must read current state first — it is a toggle, not a setter. Leave the match locked at the end; report status. Do **not** rely on lock to prevent writes (§3.7) — it only blocks public self-squadding.

---

## 6. Security observations

These were found incidentally while mapping the API. They are reported so the client library can be written defensively, and are worth reporting to PractiScore.

1. **CSRF not enforced on squadding writes.** `POST /squads/check/...` and `POST /squads/save/...` both succeeded with the `X-CSRF-TOKEN` header omitted, while carrying only the session cookie (**re-verified 2026-07-26**: `check`→`added` and `save`→`moved`, both with no CSRF header). If these routes are CSRF-exempt, any third-party page could silently re-squad a logged-in admin's match. `[V]`
2. **`/squads/save` is entirely unvalidated** — no `check` prerequisite, no occupancy check, no CSRF. It can place two shooters in one slot, hiding one from the UI (§3.4). `[V]`
3. **Unescaped SQL `LIKE` in the search path.** `_` and `%` from the URL path reach the query as wildcards. Only wildcard behavior was observed — no evidence of injection beyond `LIKE` semantics, and this was not probed further. Still indicates user input reaching a query without escaping. `[V]`
4. **Lock is not an authorization boundary** — writes succeed on a locked match (§3.7). `[V]`
5. **`page` parameter on `removeshooter`** is a caller-controlled redirect target; possible open redirect. `[I]`
6. **PII exposed to anonymous callers.** `GET /squads/registered/{anyValidSlot}/{query}` returns shooter **email addresses with no authentication whatsoever** — verified 2026-07-25 with a cookieless request (§3.2). Combined with the `%20`/`_`/`%` "list all" behavior (§3.2), the entire match roster's emails are harvestable by anyone who knows a match's `matchId` and one squad slot, both of which are discoverable. This is materially worse than "any session that can view squadding"; it is **no session at all**. Highest-severity item to report to PractiScore. `[V]`
7. **Auth boundary is inconsistent across sibling routes.** The bootstrap page (`GET /{slug}/squadding`) 302-redirects unauthenticated callers to `/login`, but its data-bearing siblings `GET /squads/registered` and `GET /squads/removeask` are reachable unauthenticated. Route-level auth is applied unevenly. `[V]`
8. **No server-side capacity or position-range enforcement (`check` add-path).** `POST /squads/check/.../{shooter}` accepted `position=7` for a squad that renders only 5 slots and **committed** the add (`{"cmd":"added"}`). The extra shooter is stored but never rendered (the UI draws only positions 1–5), producing a **hidden assignment** that is invisible to admins through the normal UI and inflates a squad past its apparent capacity. Combined with §3.4's unvalidated `save`, the server trusts client-supplied positions unconditionally. Worth reporting to PractiScore alongside the `save` double-assignment. `[V]`

---

## 7. Open questions

1. ~~`noAuth` path for `removeask`~~ **(resolved 2026-07-25: anonymous → `noAuth`, §3.5)**; ~~admin path~~ **(resolved 2026-07-26: authenticated admin → `ask`, §3.5)**. Both ends of the permission matrix are now pinned. Still open: the **middle** — distinguishing squad-lead from shooter-self-squadding, which needs a second, mid-privilege authenticated session.
2. Notification behavior of `email=1` and `send=yes` — deliberately untested to avoid emailing real people. What is sent, to whom, and does `check`'s `email` interact with `save`'s `send`?
3. Multi-schedule / multi-day matches: is `scheduleId` ever required in a request, or purely presentational?
4. ~~Squad capacity: is there a distinct "squad full" error, or only `taken` per slot?~~ **(resolved 2026-07-26, §3.3/§6.8: capacity is NOT server-enforced — `check` accepts out-of-range positions and commits them as hidden assignments; there is only per-slot `taken`, no "full" error. The 5-slot count is a per-match UI rendering.)** Still open: whether the per-match slot count is configurable, and whether squads can be **created/deleted** via API (not attempted — would alter sandbox structure).
5. Server-side enforcement of `reserved` / `disabled` slots — does `check` reject them, or only the UI?
6. Exact HTTP status and `Location` of the `removeshooter` redirect. *(2026-07-26: exercised live and succeeds, but `fetch`+`redirect:'manual'` masks it as `opaqueredirect`/`status:0`, and a CDP capture reported a contradictory `503` — §3.6. The exact `3xx` code and `Location` still need a raw client: re-test with `requests`, `allow_redirects=False`.)*
7. Concurrency semantics: two simultaneous `check` calls on the same free slot — does either lose, or do both "succeed" into a collision like §3.4?
8. Whether `shooterId` is match-scoped or global, and whether a `shooterId` from another match can be injected into this match.
9. Rate limits / Turnstile thresholds for automated clients.
10. Any additional routes in `/js/all.js` (not decompiled).

---

## 8. Discovery methodology & test log

Endpoints were located by extracting URL literals from the squadding page's inline `$(document).ready` handlers and from rendered `#delModal_*` form markup. `/js/all.js` was not decompiled.

All destructive tests ran against the sandbox match `test-reverse-engineer` and were sequenced to return to the initial layout. Notifications were suppressed (`email=0`, `send=no`) throughout so no shooter was emailed.

| # | Test | Result |
|---|---|---|
| 1 | `check` occupied slot | `{"cmd":"taken","num":1}` |
| 2 | `check` shooter's own squad, other slot | `{"cmd":"same","num":1}` |
| 3 | `check` different squad | `{"cmd":"move","num":1}` |
| 4 | `save` after `move` | `moved`; origin slot auto-vacated |
| 5 | `removeask` | `ask` |
| 6 | `removeshooter` | 3xx redirect; unsquadded, roster intact |
| 7 | `check` unsquadded shooter → free slot | `{"cmd":"added","num":1}` |
| 8 | `check` with no CSRF header | **succeeded** (200) |
| 9 | `check` bogus shooter / wrong matchId / malformed slot | `500 {"message":"Server Error"}` |
| 10 | `check` position=99, shooter in that squad | `same` — position not validated |
| 11 | `save` after `check`, occupied target | `moved` — hidden double-assignment (§3.4) |

*(Row 11's outcome is reconstructed from §3.4's `[V]` narrative; the original v2.0 test-log entry was truncated in the source file.)*

### 8.1 Re-verification log — 2026-07-25 (unauthenticated, read-only)

Run from a fresh client with only Cloudflare-issued cookies; no login, no mutations, no emails. Only non-mutating endpoints were touched.

| # | Test | Result |
|---|---|---|
| R1 | `GET /{slug}/squadding` (bootstrap) | `302 → /login` — auth-gated `[V]` |
| R2 | `GET /squads/registered/.../%20`, **no cookies, no headers** | `200 application/json`, full roster **incl. emails** — unauthenticated `[V]` |
| R3 | `registered` `a` / `_` / `%25` / `An_toli` / `An%li` / `zzzq` | `1 / 2 / 2 / 1(Anatoli) / 1(Anatoli) / []` — `LIKE` semantics reproduced `[V]` |
| R4 | `registered` pos=99 & different squad | full roster both — `squadId`/`position` ignored `[V]` |
| R5 | `registered` wrong `matchId` / malformed slot | `500 {"message":"Server Error"}` (`application/json`) `[V]` |
| R6 | `registered` empty query | `404` (`application/json`) `[V]` |
| R7 | `GET /squads/removeask?info=clearSpot_...`, **no cookies** | `200 text/html`, bare `noAuth` — resolves `noAuth` path `[V]` |
| R8 | `POST /squads/check/.../1` (bogus shooter), unauth | `500 {"message":"Server Error"}` (`application/json`) — auth-gating vs. bad-shooter not separable without risking a real add `[V]/[I]` |

Not re-tested (require an authenticated admin session, unavailable this run): `check` add/`taken`/`same`/`move` branches, `save`, `removeshooter`, `lock`. **→ All re-tested 2026-07-26; see §8.2.**

### 8.2 Re-verification log — 2026-07-26 (authenticated admin, mutating)

Run through the live admin session via in-page `fetch` (`credentials:'same-origin'`). Notifications suppressed (`email=0` / `send=no`) throughout; **no shooter was emailed**. Every mutation was paired with an inverse and the match was returned to its exact initial layout, verified slot-by-slot at the end (Grzegorz `9808574` → Squad 1 pos 1, Anatoli `9808577` → Squad 2 pos 1, Squad 3 empty, unlocked, roster n=2).

Initial state: shooters `9808574` (Grzegorz, Production, trailing-whitespace name) and `9808577` (Anatoli, Standard); both carry `email` in the roster.

| # | Test | Result |
|---|---|---|
| A1 | `GET removeask` (clearSpot, **admin**) | `200 text/html`, bare `ask` — admin branch pinned `[V]` |
| A2 | `check` Grzegorz → own squad, other slot | `{"cmd":"same","num":1}` (`text/html`) `[V]` |
| A3 | `check` Grzegorz → Anatoli's occupied slot (Sq 2) | `{"cmd":"taken","num":2}` — `num` = **target** squad `[V]` |
| A4 | `check` Grzegorz → different squad, free slot | `{"cmd":"move","num":1}` — `num` = **origin** squad `[V]` |
| A5 | `check` response keys / content-type | exactly `["cmd","num"]`; success is `text/html` (only its `500` is JSON) `[V]` |
| A6 | `removeshooter` Grzegorz (`spot_..._1_...`) | opaque `3xx` (CDP reported `503`, §3.6); unsquadded, **roster still n=2** `[V]` |
| A7 | `check` Grzegorz → now-free slot, **no CSRF header** | `{"cmd":"added","num":1}` — added path + CSRF-unenforced `[V]` |
| A8 | `check` Grzegorz → Squad 3 **pos 3** | `{"cmd":"move","num":1}` `[V]` |
| A9 | `save` Grzegorz → Squad 3 pos 3, **no CSRF header**, `send=no` | bare `moved` (5 bytes, `200`); landed at **pos 3 exactly**; origin auto-vacated `[V]` |
| A10 | `check` Grzegorz → Squad 1 (origin now Sq 3) | `{"cmd":"move","num":3}` — `num` tracks new origin `[V]` |
| A11 | `save` Grzegorz → back to Squad 1 pos 1 | `moved`; restored `[V]` |
| A12 | `POST /matches/.../lock` `matchId=351459` | `{"success":true}`; button `btn-primary`→`btn-danger` (locked) `[V]` |
| A13 | `check`→`save` move **while locked** | `move` then `moved`; **persisted** — lock is not a write interlock `[V]` |
| A14 | `POST .../lock` again | `{"success":true}`; button →`btn-primary` (unlocked) — pure toggle `[V]` |
| A15 | `removeshooter` Grzegorz, then `check` Grzegorz → **position 7** | `{"cmd":"added","num":1}` — **out-of-range add committed**; UI shows Sq 1 empty; probe `check`→`same` confirms hidden assignment `[V]` |
| A16 | `removeshooter` `spot_..._7_...` (cleanup), then `check` → pos 1 | `added`; hidden pos-7 assignment removed, Grzegorz restored `[V]` |

Not tested (out of scope / would perturb sandbox structure or email real people): squad create/delete via API, `email=1`/`send=yes` notification paths, the squad-lead/self-squad middle of the permission matrix, and cross-match `shooterId` injection.