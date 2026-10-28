# Movie Lovers

A small, self-contained web feature for film fans: search TMDB, keep a watchlist,
tick films off as watched, rate them 1-5 stars, and get up to ten similar picks
that never repeat something already on your list.

Built from scratch for this brief. **Standard library only** - no Flask, no
React, no build step, no `npm install`. About 1,082 lines of Python for the app itself and
roughly 520 for the tests.

## What it does

| Flow | Where |
|---|---|
| Search titles via the TMDB public API | `GET /search?q=` |
| Poster, title, year, TMDB rating in the results | search results grid |
| Sign up / sign in (email + password) | `GET/POST /signup`, `/login` |
| Add / remove a film on the watchlist | movie page, watchlist page |
| Mark a film watched / not watched | movie page, watchlist page |
| Rate 1-5 stars, and change the rating later | movie page (only once watched) |
| Up to 10 similar picks, excluding watchlisted films | movie page |

Out of scope, as agreed: public deployment, payments, mobile apps, social features.

## How it is built

```
run.py                 start the server (real TMDB or --demo fixtures)
test_all.py            one command, 56 tests
app/tmdb.py            TMDB client: 3 endpoints, retries, typed errors
app/store.py           SQLite: accounts, watchlist, ratings + the rules
app/pages.py           HTML rendering (string templates, escaped output)
app/server.py          http.server routing, signed session cookie
app/__init__.py
fixtures/movies.json   offline catalogue for --demo and for the tests
tools/make_screenshots.py  regenerates screenshots/ from the running app
```

Four decisions worth stating up front:

1. **No framework.** The brief allows any stack; the smallest thing that can be
   reviewed in one sitting is `http.server` plus `sqlite3`. It starts in under a
   second and has zero dependency risk on a reviewer's machine.
2. **The rules live in `store.py`, not in the HTTP layer.** A film must be on the
   watchlist before it can be watched; only watched films can be rated; re-rating
   overwrites; stars are an integer 1-5, and the SQLite schema carries a
   `CHECK (stars BETWEEN 1 AND 5)` as the last line of defence. The web layer
   cannot bypass any of it.
3. **The TMDB transport is injectable.** `TmdbClient(transport=...)` means the
   test suite never touches the network and never needs an API key, so the tests
   run the same way on a reviewer's machine, in CI, and on an air-gapped box.
4. **Similar picks are filtered after fetching, then capped.** TMDB returns
   candidates; we drop anything already on *that user's* watchlist, then take the
   first 10. Filtering before capping is what makes the acceptance line
   ("never include movies already on the watchlist") hold even when most
   candidates are already saved.

## Run it

```bash
export TMDB_API_KEY=<your key>     # free: https://www.themoviedb.org/settings/api
python3 run.py
# -> listening: http://127.0.0.1:8000
```

No key yet, or offline? `python3 run.py --demo` runs the same app against
`fixtures/movies.json` (9 films) and draws local placeholder posters, so every
screen can be seen without a network call.

Full instructions, including tests and troubleshooting: **[SETUP.md](SETUP.md)**.
Plain-language walkthrough for a non-technical user: **[USER_GUIDE.md](USER_GUIDE.md)**.

## Test it

```bash
python3 test_all.py
```

56 tests, ~2 seconds, no network, no key. They cover the watchlist and rating
rules (as required), the similar-picks exclusion, the TMDB client's retry and
error handling, and four end-to-end HTTP flows against a live server on a random
port.

## Screens

`screenshots/` holds one distinct image per flow (the generator fails if two turn out
byte-identical), regenerated with
`python3 tools/make_screenshots.py` (headless Edge/Chrome). The pages in them are
the exact HTML the server returned during the scripted run.

| File | Flow |
|---|---|
| `00-welcome.png` | the welcome screen (signed out) |
| `01-search.png` | searching "alien" |
| `02-movie-detail.png` | a film page: add, mark watched, remove |
| `03-ratings.png` | a 3/5 rating, changeable |
| `04-watchlist.png` | the watchlist with watched state and ratings |
| `05-similar-picks.png` | similar picks with watchlisted titles removed |

## What was verified, and what was not

This is the sentence that matters most in this README, so it is not buried:

- **Verified here**: the whole app, end to end, in **`--demo` mode** and in the test
  suite, on **Windows 11 / Python 3.11.7** and **Ubuntu 24.04 / Python 3.12.3**.
  56 tests pass from a clean unzip on both, and the six screenshots are rendered
  from a real running server on both.
- **Not verified by me: a live call to `api.themoviedb.org`.** From the machine
  this was written on, TMDB's API host resolves to a poisoned address
  (`192.133.77.197`, plus a fake `face:b00c::` IPv6) and every request times out;
  public DNS-over-HTTPS endpoints are blocked there too. I never had a TMDB key,
  so the live path has been exercised only against fakes that reproduce TMDB's
  documented response shapes - not against the real service.

  What this means for you: the first live run is yours. If TMDB answers anything
  unexpected, the failure will be a clean message (`TMDB rejected the API key`,
  `cannot reach TMDB`, or `TMDB returned HTTP 4xx`), not a traceback. If it turns
  out the real payload differs from what I assumed, that is a bug I owe you.

## Known limitations

Stated plainly, because they are the questions a reviewer will ask:

- **Sessions are a signed cookie, not a server-side session table.** Signing out
  clears the cookie on your browser; a copy taken before that stays valid until
  it expires (30 days). Fine for a local feature, not for a public deployment.
- **No CSRF token on the POST forms.** The cookie is `SameSite=Lax`, which blocks
  cross-site form posts in current browsers, but a real deployment should add a
  token. Local-only scope was the trade.
- **No email verification, no password reset, no login rate limiting.** The brief
  asked for "simple email + password accounts"; this is that, no more.
- **Posters are hot-linked from `image.tmdb.org`.** In `--demo` mode they are
  generated locally instead.
- **`--demo` fixtures are a fixed catalogue of 9 films.** They exist to make the
  app reviewable offline; search there only matches those titles.
- **TMDB attribution.** If this ever ships publicly, TMDB's terms require their
  logo and the line "This product uses the TMDB API but is not endorsed or
  certified by TMDB". Not included here because nothing is deployed.
