# SETUP - install, configure, run, test

Every command below was run on Windows 11 (Python 3.11.7) and Ubuntu 24.04
(Python 3.12.3). Nothing outside the Python standard library is needed.

## 1. Requirements

- Python 3.9 or newer, on any OS. Check with `python3 --version`.
- No `pip install` step. There are no third-party packages.
- A free TMDB API key (only for live mode). Get one at
  <https://www.themoviedb.org/settings/api> - it is the "API Key (v3 auth)"
  value, a 32-character hex string.

## 2. Get the code and enter the directory

```bash
unzip movie-lovers.zip
cd movie-lovers
```

(If you cloned a git repository instead, `cd` into it.)

## 3. Configure the TMDB key

The key is read from an environment variable, never from a file in the repo.

```bash
# macOS / Linux
export TMDB_API_KEY=0123456789abcdef0123456789abcdef

# Windows PowerShell
$env:TMDB_API_KEY = "0123456789abcdef0123456789abcdef"

# Windows cmd.exe
set TMDB_API_KEY=0123456789abcdef0123456789abcdef
```

Use your own key. The value above is a placeholder and will return HTTP 401.

## 4. Run it

```bash
python3 run.py
```

Expected output:

```
Movie Lovers - live TMDB
db      : <path>/data/movies.db
listening: http://127.0.0.1:8000
stop     : Ctrl+C
```

Open <http://127.0.0.1:8000>. Stop it with `Ctrl+C`.

### Options

| Flag | Meaning |
|---|---|
| `--demo` | offline mode: `fixtures/movies.json` instead of TMDB, locally drawn placeholder posters, no key needed |
| `--port 8080` | listen somewhere else (default 8000) |
| `--db /path/file.db` | database location (default `data/movies.db`, created on first run) |
| `--host 0.0.0.0` | bind to all interfaces (default `127.0.0.1`, local only) |
| `--quiet` | no per-request log lines |

No key to hand? This proves the app is wired up end to end:

```bash
python3 run.py --demo
```

Then search for `alien`. You will see six fixture films (the offline catalogue
holds nine titles in total) instead of live TMDB
data - the UI, the watchlist, the ratings and the similar-picks filter all
behave identically.

## 5. Run the tests

```bash
python3 test_all.py
```

Expected tail:

```
test classes: Concurrency, ErrorFeedback, HttpFlows, SimilarPicks, StoreAccounts,
StoreRatings, StoreWatchlist, TmdbClientBehaviour
Ran 56 tests in ~2s

OK
```

Exit code is `0` on success and `1` on failure, so it drops straight into CI.
The suite needs no network and no API key: the TMDB transport is faked.

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `[!] TMDB_API_KEY is not set.` and exit code 2 | The variable is not in this shell. Re-run step 3, then confirm with `python3 -c "import os;print(bool(os.environ.get('TMDB_API_KEY')))"` |
| `TMDB rejected the API key (HTTP 401)` | Wrong key, or a "read access token" was pasted instead of the v3 API key |
| `cannot reach TMDB` | No outbound HTTPS from this machine. Use `--demo` to confirm the app itself works, then fix network access |
| `[!] cannot listen on 127.0.0.1:8000` | Port taken. Use `--port 8080` |
| Search returns nothing for a title you know | TMDB search wants the original title. Try a shorter fragment |
| A star rating button does nothing | The film must be marked watched first; the movie page says so |

## 7. Where state lives

Two files appear next to the database, both ignored by git:

- `data/movies.db` - SQLite: accounts, watchlists, ratings. Delete it to start over
  with no accounts and no watchlists.
- `data/movies.db.secret` - the random key used to sign the session cookie. It is
  created on first run and reused afterwards, which is why a restart does **not**
  log you out. Delete it to invalidate every existing session. Passwords are stored
as PBKDF2-HMAC-SHA256, 120,000 iterations, per-user random salt - never in clear.

## 8. Regenerating the screenshots (optional)

```bash
python3 tools/make_screenshots.py
```

Starts the app in `--demo` on a free port, drives the real HTTP endpoints
(signup, add, watched, rate), saves the returned HTML, and renders it with
headless Edge or Chrome. Requires a Chrome/Edge/Chromium binary on the machine;
if none is found the script says so and changes nothing under `screenshots/`.
