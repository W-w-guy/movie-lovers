#!/usr/bin/env python3
"""Movie Lovers - start the app.

    python3 run.py                 real TMDB (needs TMDB_API_KEY)
    python3 run.py --demo          offline fixtures, no key, no network

Open http://127.0.0.1:8000 after it prints "listening".
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app import pages                       # noqa: E402
from app.server import make_server           # noqa: E402
from app.store import Store                  # noqa: E402
from app.tmdb import TmdbClient              # noqa: E402


class FixtureTransport:
    """Serves the three TMDB endpoints from fixtures/movies.json."""

    def __init__(self, path=None):
        path = path or os.path.join(HERE, "fixtures", "movies.json")
        with open(path, encoding="utf-8") as fh:
            self.data = json.load(fh)
        self.movies = self.data.get("movies", {})

    def get(self, url, params, timeout=None):
        path = url.split("/3", 1)[-1] if "/3" in url else url
        path = path.split("?")[0]
        if path == "/search/movie":
            query = str(params.get("query", "")).strip().lower()
            table = self.data.get("search", {})
            ids = table.get(query)
            if ids is None:
                ids = [int(k) for k, v in self.movies.items()
                       if query and query in (v.get("title") or "").lower()]
            return 200, {"results": [self.movies[str(i)] for i in ids
                                     if str(i) in self.movies]}
        if path.startswith("/movie/") and path.endswith("/recommendations"):
            mid = path.split("/")[2]
            ids = self.data.get("recommendations", {}).get(mid, [])
            return 200, {"results": [self.movies[str(i)] for i in ids
                                     if str(i) in self.movies]}
        if path.startswith("/movie/"):
            mid = path.split("/")[2]
            if mid in self.movies:
                return 200, self.movies[mid]
            return 404, {"status_message": "not found"}
        return 404, {"status_message": "fixture has no route for " + path}


def poster_svg(mid, title):
    """Deterministic placeholder poster, used only in --demo mode."""
    digest = hashlib.sha256(str(mid).encode()).hexdigest()
    hue = int(digest[:4], 16) % 360
    safe = pages.esc(title or ("Movie %s" % mid))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="342" height="513" '
            'viewBox="0 0 342 513" role="img" aria-label="%s">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="hsl(%d,46%%,28%%)"/>'
            '<stop offset="1" stop-color="hsl(%d,52%%,12%%)"/></linearGradient></defs>'
            '<rect width="342" height="513" fill="url(#g)"/>'
            '<text x="24" y="440" fill="#e8eaed" font-family="sans-serif" '
            'font-size="26" font-weight="700">%s</text>'
            '<text x="24" y="472" fill="#9fb4c7" font-family="sans-serif" '
            'font-size="15">demo poster</text></svg>' % (safe, hue, (hue + 40) % 360, safe))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the Movie Lovers web app.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=os.path.join(HERE, "data", "movies.db"))
    ap.add_argument("--demo", action="store_true",
                    help="offline fixtures + placeholder posters; no key, no network")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    store = Store(args.db)
    if args.demo:
        tmdb = TmdbClient(api_key="demo", transport=FixtureTransport())
        poster_fn = lambda mid: poster_svg(mid, _title(store, mid))
    else:
        tmdb = TmdbClient()
        poster_fn = None
        if not tmdb.has_key():
            print("[!] TMDB_API_KEY is not set.", file=sys.stderr)
            print("    export TMDB_API_KEY=<your key>   (free: "
                  "https://www.themoviedb.org/settings/api)", file=sys.stderr)
            print("    or run: python3 run.py --demo   (offline fixtures)", file=sys.stderr)
            return 2

    try:
        httpd = make_server(store, tmdb, args.host, args.port, poster_fn=poster_fn)
    except OSError as exc:
        print("[!] cannot listen on %s:%d - %s" % (args.host, args.port, exc),
              file=sys.stderr)
        print("    pick another port: python3 run.py --port 8080", file=sys.stderr)
        store.close()
        return 3
    httpd.quiet = args.quiet
    mode = "DEMO (offline fixtures)" if args.demo else "live TMDB"
    print("Movie Lovers - %s" % mode)
    print("db      : %s" % args.db)
    print("listening: http://%s:%d" % (args.host, args.port))
    print("stop     : Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
        store.close()
    return 0


def _title(store, mid):
    for row in store.conn.execute("SELECT title FROM watchlist WHERE movie_id=?", (int(mid),)):
        if row["title"]:
            return row["title"]
    try:
        with open(os.path.join(HERE, "fixtures", "movies.json"), encoding="utf-8") as fh:
            return (json.load(fh).get("movies", {}).get(str(mid), {}) or {}).get("title") or ""
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
