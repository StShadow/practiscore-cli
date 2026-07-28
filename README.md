# practiscore-squads

A command-line tool to manage [PractiScore](https://practiscore.com) match squads programmatically — list squads, list shooters, and move shooters (one or many) between squads.

Built for match staff who need to reorganize squadding in bulk instead of dragging names one at a time in the web UI.

> **Design docs:** [`spec.md`](./spec.md) (requirements + reverse-engineered API) · [`implementation.md`](./implementation.md) (architecture + CLI reference).

---

## What it does

| Command | Purpose |
|---|---|
| `squads` | List all squads with occupancy |
| `shooters` | List the roster as `(name, ID)` — whole match or one squad |
| `move` | Move one shooter (by ID) to a squad |
| `move-bulk` | Move a list of shooters to a squad, with progress + resume |
| `config set-default` | Save a default match so you don't retype it |

Safe by default: it **previews and asks before changing anything**, **never emails shooters** unless you opt in, and **locks the match** while it works. Big runs (hundreds of shooters) show a progress bar and can be **resumed** if interrupted.

---

## Requirements

- **Python 3.11+**
- A PractiScore account with **admin access to the match** you want to manage
- A logged-in **browser session cookie** (see below) — the tool has no separate login of its own

---

## Install (v1 — run from the repo)

```bash
git clone <this-repo> practiscore-lib
cd practiscore-lib
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e .
```

Run it as:

```bash
python -m practiscore_squads --help
# or the installed alias:
practiscore-squads --help
```

---

## Authentication — getting your session cookie

PractiScore has **no API keys**. The only way to authenticate is with the session cookie from a browser where you're already logged in. You copy that cookie once and hand it to the tool; the tool acts as "you" for as long as the cookie is valid.

> **Treat this cookie like your password.** Anyone who has it can act as you on PractiScore. Don't paste it into chats, don't commit it to git, and don't share the file you store it in. It also **expires** (typically hours to a couple of weeks) — when the tool says your session expired, just grab a fresh one the same way.

You want to copy the **entire `Cookie` request header**, not a single cookie. That header includes the Laravel session *and* the Cloudflare clearance cookies the site needs to let an automated client through. The most reliable way to get the whole header is the browser's Network tab.

### Firefox

1. Log in to **practiscore.com** and open your match's squadding page:
   `https://practiscore.com/<your-match-slug>/squadding`
2. Press **F12** to open Developer Tools, and click the **Network** tab.
3. **Reload the page** (**Ctrl+R** / **Cmd+R**) so requests appear.
4. In the request list, click the **first/top request** — the HTML document (its name is your match slug or `squadding`, Type `html`).
5. In the panel that opens, select **Headers**, then scroll to **Request Headers**.
6. Find the **`Cookie`** row. Right-click it → **Copy** (or click the value and copy it). You want the full value, e.g. `XSRF-TOKEN=…; laravel_session=…; cf_clearance=…`.
7. Save it — see [Using the cookie](#using-the-cookie) below.

> Tip: if the Cookie value is truncated in the view, right-click the request → **Copy** → **Copy Request Headers**, then keep only the `Cookie:` line's value.

### Chrome (and Edge / Brave)

1. Log in to **practiscore.com** and open your match's squadding page:
   `https://practiscore.com/<your-match-slug>/squadding`
2. Press **F12** to open DevTools, and click the **Network** tab.
3. **Reload the page** (**Ctrl+R** / **Cmd+R**).
4. In the request list, click the **top document request** (Name = your match slug / `squadding`, Type `document`).
5. Select the **Headers** tab, scroll to **Request Headers**, and find **`cookie`**.
6. Right-click the `cookie` entry → **Copy value** (newer Chrome), or select the value text and **Ctrl+C**.
7. Save it — see below.

> If you don't see `cookie` under Request Headers, click the **"Raw"** toggle next to Request Headers to show the raw header text, then copy the `cookie:` line's value.

### Using the cookie

Pick whichever fits your workflow. The tool looks for the cookie in this order: `--cookie` → `PRACTISCORE_COOKIE` env var → config file → interactive prompt.

**Option A — from a file (recommended):** paste the value into a local file (e.g. `cookie.txt`, and add it to `.gitignore`), then:

```bash
practiscore-squads --cookie @cookie.txt squads
```

**Option B — environment variable:**

```bash
# Windows PowerShell:
$env:PRACTISCORE_COOKIE = "XSRF-TOKEN=…; laravel_session=…; cf_clearance=…"
# macOS/Linux:
export PRACTISCORE_COOKIE="XSRF-TOKEN=…; laravel_session=…; cf_clearance=…"

practiscore-squads squads
```

**Option C — inline** (least safe; it lands in your shell history):

```bash
practiscore-squads --cookie "XSRF-TOKEN=…; laravel_session=…" squads
```

> **Note on Cloudflare:** the `cf_clearance` cookie is tied to the browser it came from. Run the tool from the **same machine/network** you used to grab the cookie for best results. If requests start failing right after copying a fresh cookie, re-copy it and try again.

---

## Quick start

```bash
# 1. Save your match as the default so you don't repeat --match
practiscore-squads config set-default --match my-club-match-2026

# 2. See the squads
practiscore-squads --cookie @cookie.txt squads

# 3. Find shooter IDs
practiscore-squads --cookie @cookie.txt shooters

# 4. Move one shooter to Squad 3 (previews and asks first)
practiscore-squads --cookie @cookie.txt move 9808574 --to 3

# 5. Move a whole list into Squad 3 from a file, no prompt
practiscore-squads --cookie @cookie.txt --yes move-bulk --to 3 --ids-file squad3.txt
```

`squad3.txt` is one shooter ID per line (`#` starts a comment):

```
# Squad 3 roster
9808574
9808577
```

---

## Common options

Global (put **before** the command):

| Option | Meaning |
|---|---|
| `--match <slug\|url>` | Target match; overrides the saved default. Slug or full squadding URL. |
| `--cookie <value\|@file>` | Session cookie (see above). |
| `--json` | Machine-readable JSON output instead of tables. |
| `--yes` / `-y` | Skip the confirmation prompt (for scripting). |
| `--notify` | **Email** shooters about their move (default: silent — no emails). |

`move` and `move-bulk` both also take `--dry-run` (print the plan and exit `0` without executing). `move-bulk` extras: `--ids a,b,c` or `--ids-file <path>`, `--fresh` (ignore a saved resume checkpoint).

Exit codes: `0` success · `1` runtime error · `2` usage error · `3` auth/session expired · `4` partial failure (`move` returned `taken`/blocked, or a bulk run had ≥1 failure) · `5` `move-bulk` stopped on throttling (resumable from checkpoint) · `130` declined the confirm prompt.

Full reference: [`implementation.md` §5–§6](./implementation.md).

---

## How it keeps your data safe

- **Preview + confirm:** every move is shown before it happens; nothing changes until you say yes (or pass `--yes`).
- **No accidental emails:** shooters are never notified unless you add `--notify`.
- **Locking:** the tool locks the match before making changes and **leaves it locked**, printing the lock status at the end. (Locking stops shooters from self-squadding on the website — it does **not** stop another *admin* working the same match at the same time.)
- **Resumable:** a big `move-bulk` checkpoints its progress; if it's interrupted (or your cookie expires), re-run the same command and it continues where it left off.
- **Audit log:** every attempted move is written to a local audit file (`~/.practiscore-squads/audit/<slug>.jsonl`) so you have a record. This file **contains shooter email addresses** — keep it local and don't share or commit it.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `session expired` / prompted for a new cookie | Grab a fresh cookie (steps above) and paste it. A `move-bulk` resumes automatically. |
| Exits with "no match" | Pass `--match <slug>` or run `config set-default --match <slug>`. |
| Requests failing / throttled right after copying cookie | Re-copy the **whole** Cookie header from the same browser/machine; ensure `cf_clearance` is included. |
| Non-ASCII names look garbled (Windows) | Use Windows Terminal / a UTF-8 console; the tool forces UTF-8 output but the terminal must support it. |
| A bulk run reports failures | It finishes everything it can and lists what failed and why (e.g. squad full). Fix and re-run — done shooters are skipped. |

---

## Running the tests

The suite uses `pytest` with [`responses`](https://github.com/getsentry/responses) to mock every PractiScore endpoint, so **no network or live cookie is needed**. Test config lives in `pyproject.toml` (`testpaths = tests`, and sandbox/live tests are excluded by default via `-m 'not sandbox'`).

Install the package with its dev extras, then run pytest:

```bash
# from the repo root, inside your virtualenv
pip install -e ".[dev]"      # installs the package + pytest, responses, ruff

pytest                        # whole suite
pytest -q                     # quieter
pytest tests/test_client_move.py            # one file
pytest tests/test_client_move.py::test_move_added -x -v   # one test, verbose, stop on first failure
```

Handy flags: `-k <expr>` selects tests by name, `--lf` reruns only the last failures, `-ra` prints a summary of skips/failures.

> **Note:** the package (library core + CLI) is fully implemented — `pip install -e ".[dev]"` puts it on the path and the whole suite runs offline against mocked endpoints. A `sandbox`-marked, opt-in suite also exists for exercising real reads against the `test-reverse-engineer` match; it needs `PRACTISCORE_COOKIE` and is excluded by default (`-m 'not sandbox'`).

> **Interpreter:** any **Python 3.11+** works. If your default `python` is older, invoke a newer one explicitly, e.g. `C:\Python314\python -m pytest`.

---

## Scope (v1)

**In:** list squads, list shooters, single move, bulk move, one match at a time, selected by slug/URL.
**Out (for now):** creating/deleting squads, a "list my matches" picker, a standalone `.exe`, and automated login. See [`spec.md` §0.4](./spec.md).

---

## Disclaimer

This is an **unofficial** tool that automates the PractiScore web interface; it is not affiliated with or endorsed by PractiScore. It depends on undocumented behavior of the site that can change without notice. Use it only on matches you administer, and review the previews before confirming.
