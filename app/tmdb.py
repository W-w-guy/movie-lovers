"""TMDB client.

Stdlib only. The HTTP transport is injectable so the test suite never touches
the network and never needs an API key.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w342"
TIMEOUT = 10


class TmdbError(Exception):
    """Base class for every error this module raises."""


class TmdbConfigError(TmdbError):
    """TMDB_API_KEY is missing or still the placeholder value."""


class TmdbAuthError(TmdbError):
    """TMDB rejected the key (HTTP 401)."""


class TmdbNetworkError(TmdbError):
    """The request never produced a usable response."""


def _clean(d):
    """Normalise one TMDB movie record to the four fields the UI shows."""
    if not isinstance(d, dict):
        return None
    mid = d.get("id")
    if not isinstance(mid, int):
        return None
    release = d.get("release_date") or ""
    year = release[:4] if len(release) >= 4 and release[:4].isdigit() else None
    rating = d.get("vote_average")
    try:
        rating = round(float(rating), 1) if rating is not None else None
    except (TypeError, ValueError):
        rating = None
    poster = d.get("poster_path")
    return {
        "id": mid,
        "title": (d.get("title") or d.get("name") or "").strip(),
        "year": year,
        "rating": rating,
        "poster": (IMG + poster) if isinstance(poster, str) and poster else None,
        "overview": (d.get("overview") or "").strip(),
    }


class UrllibTransport:
    """Real network transport. Returns (status, json_body_or_None)."""

    def get(self, url, params, timeout=TIMEOUT):
        query = urllib.parse.urlencode(params, safe="+")
        full = url + ("&" if "?" in url else "?") + query
        req = urllib.request.Request(full, headers={"Accept": "application/json",
                                                   "User-Agent": "movie-lovers/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            status = exc.code
        except Exception as exc:
            raise TmdbNetworkError("cannot reach TMDB: %s: %s"
                                   % (type(exc).__name__, exc))
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, None


class TmdbClient:
    def __init__(self, api_key=None, transport=None, base=BASE,
                 retries=2, sleep=time.sleep):
        import os
        key = api_key if api_key is not None else os.environ.get("TMDB_API_KEY", "")
        self.key = (key or "").strip()
        self.base = base.rstrip("/")
        self.transport = transport or UrllibTransport()
        self.retries = max(0, int(retries))
        self.sleep = sleep

    def has_key(self):
        return bool(self.key) and self.key != "your_tmdb_api_key"

    def _get(self, path, params):
        if not self.has_key():
            raise TmdbConfigError(
                "TMDB_API_KEY is not set. Get a free key at "
                "https://www.themoviedb.org/settings/api and export it.")
        query = dict(params)
        query["api_key"] = self.key
        url = self.base + path
        attempt = 0
        while True:
            status, body = self.transport.get(url, query)
            if status == 200 and isinstance(body, dict):
                return body
            if status == 401:
                raise TmdbAuthError("TMDB rejected the API key (HTTP 401).")
            if status == 404:
                raise TmdbError("not found: %s" % path)
            retryable = status == 429 or status >= 500 or status == 0
            if retryable and attempt < self.retries:
                attempt += 1
                self.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            raise TmdbError("TMDB returned HTTP %s for %s" % (status, path))

    def search(self, query, limit=20):
        query = (query or "").strip()
        if not query:
            return []
        body = self._get("/search/movie", {"query": query, "include_adult": "false"})
        out = []
        for raw in (body.get("results") or [])[:limit]:
            item = _clean(raw)
            if item:
                out.append(item)
        return out

    def movie(self, movie_id):
        body = self._get("/movie/%s" % int(movie_id), {})
        item = _clean(body)
        if item is None:
            raise TmdbError("unusable movie payload for id %s" % movie_id)
        return item

    def recommendations(self, movie_id, limit=20):
        body = self._get("/movie/%s/recommendations" % int(movie_id), {})
        out = []
        for raw in (body.get("results") or [])[:limit]:
            item = _clean(raw)
            if item:
                out.append(item)
        return out
