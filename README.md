# Fast Simon – New Hire Challenge

Both tasks run on Google App Engine (Standard Environment, Python 3.12) in the project `negev-fast-simon`.

| Task | Live URL | Code |
|---|---|---|
| I – Hello World | https://negev-fast-simon.ew.r.appspot.com/ | [`task1/`](task1) |
| II – Simple database | https://db-dot-negev-fast-simon.ew.r.appspot.com/ | [`task2/`](task2) |

> New App Engine apps get a region code in their URL (`.ew.r` = europe-west), so the URLs look slightly different from the `your-app-id.appspot.com` format in the instructions.
> Task II is deployed as a separate App Engine service (`db`), so both tasks stay live side by side.

---

## Task I – Hello World

The app from the App Engine quickstart: a Flask app whose `/` route returns `Hello World!`.

- `main.py` – the Flask app
- `app.yaml` – App Engine config (`python312`, capped at one F1 instance to stay in the free tier)
- `requirements.txt` – Flask and gunicorn

---

## Task II – Simple database

### Commands

| Command | Example | Output |
|---|---|---|
| SET | `/set?name=a&value=10` | `a = 10` |
| GET | `/get?name=a` | `10`, or `None` if not set |
| UNSET | `/unset?name=a` | `a = None` |
| NUMEQUALTO | `/numequalto?value=10` | number of variables equal to `10` |
| UNDO | `/undo` | the changed variable after the undo, or `NO COMMANDS` |
| REDO | `/redo` | the changed variable after the redo, or `NO COMMANDS` |
| END | `/end` | deletes all data, then `CLEANED` |

Opening `/` shows the list of commands.

### Code structure

| File | Responsibility |
|---|---|
| `main.py` | Flask handlers for the commands, input validation and error handling |
| `database.py` | The database logic: data model, undo/redo history, value counters |
| `storage.py` | Storage layer: Google Cloud Datastore, plus an in-memory store for tests |
| `tests/test_app.py` | Tests: the 3 sequences from the instructions, edge cases, the extra feature |
| `smoke_test.py` | Runs the same tests over HTTP against the deployed app |

`database.py` knows nothing about HTTP or Datastore, so the logic can be tested quickly without any cloud access.

### Data model

Four Datastore kinds:

| Kind | Key | Fields | Purpose |
|---|---|---|---|
| `Variable` | variable name | `value` | The variables themselves |
| `ValueCount` | value | `count` | How many variables currently hold this value |
| `Command` | 1, 2, 3, … | `name`, `old_value`, `new_value` | History of SET/UNSET commands |
| `State` | `"state"` | `cursor`, `top` | `cursor` = number of commands currently applied; `top` = last command that can be redone |

**NUMEQUALTO** reads a single `ValueCount` entity instead of scanning all variables. Every change updates the counters of the old and new value.

**UNDO / REDO** work like a browser's Back / Forward buttons over the `Command` history:

- **SET / UNSET** write a new command at `cursor + 1` and set `top = cursor`. Any commands after it (undone ones) can no longer be redone – they are simply ignored and later overwritten, so nothing has to be deleted.
- **UNDO**: if `cursor == 0` → `NO COMMANDS`. Otherwise restore `old_value` of command `#cursor` and decrement `cursor`.
- **REDO**: if `cursor == top` → `NO COMMANDS`. Otherwise increment `cursor` and re-apply `new_value` of command `#cursor`.

Example – steps of sequence 3 from the instructions (GETs omitted):

| Request | Variables | Commands | cursor / top | Output |
|---|---|---|---|---|
| `set a=10` | a=10 | #1 a: None→10 | 1 / 1 | `a = 10` |
| `set b=20` | a=10, b=20 | #1, #2 b: None→20 | 2 / 2 | `b = 20` |
| `undo` | a=10 | #1, #2 | 1 / 2 | `b = None` |
| `set a=40` | a=40 | #1, #2 **a: 10→40** (overwrites) | 2 / 2 | `a = 40` |
| `undo` | a=10 | | 1 / 2 | `a = 10` |
| `undo` | – | | 0 / 2 | `a = None` |
| `undo` | – | | 0 / 2 | `NO COMMANDS` |
| `redo` | a=10 | | 1 / 2 | `a = 10` |
| `redo` | a=40 | | 2 / 2 | `a = 40` |

### Complexity

Every command except END reads and writes a fixed number of entities, always by key – no queries, no scans:

| Command | Reads | Writes |
|---|---|---|
| GET, NUMEQUALTO | 1 | 0 |
| SET, UNSET | state + variable, then up to 2 counters (2 batched round trips) | variable, up to 2 counters, command, state |
| UNDO, REDO | state, command, up to 2 counters | variable, up to 2 counters, state |
| END | one keys-only query per kind | delete everything – O(n), as allowed |

So all commands except END are **O(1)**.

Every command that changes data runs in a single **Datastore transaction**, so the variable, its counters and the history can never get out of sync – even if a request fails half way.

### Handling unexpected input

- Missing or empty `name` / `value` → HTTP 400 with an explanation and the list of commands.
- Names/values containing spaces, longer than 500 bytes, or of the form `__x__` (reserved by Datastore) → HTTP 400.
- Unknown path → HTTP 404 with the list of commands; non-GET methods → HTTP 405.
- An invalid request never changes any data.
- Unexpected server errors are logged and return a short HTTP 500 message, never a stack trace.

---

## Extra feature: isolated databases (`db` parameter)

Any command accepts an optional `db` parameter that selects a separate, isolated database:

```
/set?name=a&value=10&db=alice
/get?name=a&db=alice        → 10
/get?name=a                 → None   (the default database is untouched)
/undo?db=alice              → a = None
/end?db=alice               → CLEANED (only alice's data is deleted)
```

Without `db`, the app behaves exactly as the instructions describe.

### Why it improves the app

In the original design **everyone shares one database**, including the undo/redo history. If two people use the app at the same time – for example two reviewers running the test sequences – they break each other's results:

| Who | Request | Result |
|---|---|---|
| A | `set a=10` | a = 10 |
| B | `set ex=10` | ex = 10 |
| A | `undo` | A expects `a = None` but gets **`ex = None`** – B's command was undone |
| B | `end` | **A's data is deleted** in the middle of A's work |

With `db`, each user gets their own variables, counters and undo/redo history, so users can no longer interfere with each other. The same idea is used by real systems (Redis numbered databases, SQL schemas, per-customer data in SaaS products – "multi-tenancy").

### How it works

It uses Datastore's built-in **namespaces**: every key includes a namespace, and reads and queries only ever see entities in their own namespace. The app passes the `db` value as the namespace of every key it builds (`storage.py`), and END deletes only the entities of that namespace. `database.py` doesn't know namespaces exist – every database automatically gets its own copy of the four kinds.

- All commands stay O(1) – the namespace is simply part of the key.
- `db` names may contain letters, digits, `.`, `_` and `-` (up to 100 characters, not starting with `__`), following Datastore's rules.
- **END clears only the database it is called on**: `/end` clears the default database, `/end?db=alice` clears only alice's. This keeps the isolation meaningful – one user can't wipe everyone else's data.
- This is isolation, not security: anyone who knows a `db` name can use it. Real access control would need authentication, which is outside the scope of this task.

---

## Decisions and known limitations

- **Sequence 3, step 8** has an empty expected output in the instructions; the app returns `a = 40`, consistent with every other SET.
- **Only SET/UNSET drop the redo history.** GET and NUMEQUALTO don't change data, so they don't count as "another command" for REDO – this matches the example sequences.
- **Every SET/UNSET is recorded**, even when it doesn't change anything (e.g. setting the same value twice, or unsetting a missing variable), so UNDO always reverts exactly the latest command.
- **Values are plain strings**: `10` and `010` are different values. Setting a variable to the text `None` can't be told apart from an unset variable by GET.
- **In URLs, `+` means a space**, so `name=a+b` is rejected as containing a space (use `%2B` for a literal `+`).
- **Concurrent requests** (which the instructions say to ignore) can't corrupt data thanks to the transactions; if two changes collide, one of them fails with "please try again".

---

## Running locally

Requires Python 3.12+.

```bash
cd task2
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# Unit tests (in-memory store, no Google Cloud access needed)
.venv/bin/python -m pytest

# Tests against the deployed app (note: calls /end on it)
.venv/bin/python smoke_test.py https://db-dot-negev-fast-simon.ew.r.appspot.com
```

## Deploying

```bash
gcloud config set project negev-fast-simon
(cd task1 && gcloud app deploy)            # default service
(cd task2 && gcloud app deploy app.yaml)   # "db" service
```
