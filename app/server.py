"""HTTP layer. http.server + http.cookies, no framework.

Routes
  GET  /                     landing + search box
  GET  /search?q=            TMDB title search
  GET  /movie/<id>           detail, your rating, similar picks
  GET  /watchlist            your saved titles
  GET  /login /signup
  POST /signup /login /logout
  POST /watchlist/add /watchlist/remove /watchlist/watched
  POST /rate
  GET  /healthz              {"ok":true,...} for smoke tests
"""
import hashlib
import hmac
import http.cookies
import json
import os
import secrets
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import pages
from .tmdb import (TmdbAuthError, TmdbConfigError, TmdbError as _TmdbError,
                    TmdbNetworkError)
from .store import AuthError, NotOnWatchlist, NotWatched, StoreError

FLASH_OK = {
    "added": "Added to your watchlist.",
    "removed": "Removed from your watchlist.",
    "watched": "Marked as watched. You can rate it now.",
    "unwatched": "Marked as not watched.",
    "rated": "Your rating was saved.",
    "signed_up": "Welcome! Your account is ready.",
    "signed_in": "Signed in.",
    "signed_out": "Signed out.",
}

# 失败也用一条明确的话回给用户；早先这些码没有对应文案，页面静默不报错。
FLASH_ERR = {
    "not_on_watchlist": "That film is not on your watchlist yet.",
    "not_watched": "Mark the film as watched before rating it.",
    "bad_rating": "Ratings go from 1 to 5 stars.",
    "invalid": "That action could not be completed.",
}


def session_secret(db_path):
    """Persist the cookie-signing secret next to the database.

    ★ 2026-10-28 修：原来 `secret or secrets.token_hex(32)` 每次启动都换一把新钥匙，
      于是重启服务 = 所有已登录用户被静默登出，而账号和收藏都还在。
      一个"重启就掉登录"的站，客户第一次重启就会来问。
      落盘 + 权限 600（POSIX；Windows 上 chmod 只影响可写位，这里尽力而为）。
    """
    seed = os.path.abspath(db_path or "movies.db") + ".secret"
    try:
        if os.path.exists(seed):
            value = open(seed, "rb").read().strip()
            if len(value) >= 32:
                return value.decode("ascii", "replace")
    except OSError:
        pass
    value = secrets.token_hex(32)
    try:
        directory = os.path.dirname(os.path.abspath(seed))
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd = os.open(seed, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(value)
        try:
            os.chmod(seed, 0o600)
        except OSError:
            pass
    except OSError:
        pass              # 写不了就退回每次随机，功能不因权限问题报废
    return value


def make_server(store, tmdb, host="127.0.0.1", port=8000, secret=None, poster_fn=None):
    secret = secret or session_secret(getattr(store, "path", ""))
    handler = _build_handler(store, tmdb, secret, poster_fn)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def _build_handler(store, tmdb, secret, poster_fn=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MovieLovers/1.0"
        protocol_version = "HTTP/1.1"

        # ---------- plumbing ----------
        def log_message(self, fmt, *args):
            if not getattr(self.server, "quiet", False):
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
            raw = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or []):
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _redirect(self, location, cookie=None):
            headers = [("Location", location)]
            if cookie:
                headers.append(("Set-Cookie", cookie))
            self._send(303, b"", headers=headers)

        def _cookie(self, value, max_age=30 * 24 * 3600):
            return ("ml_session=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d"
                    % (value, max_age))

        def _sign(self, user_id):
            mac = hmac.new(secret.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
            return "%d.%s" % (user_id, mac[:32])

        def _uid(self):
            raw = http.cookies.SimpleCookie(self.headers.get("Cookie", "")).get("ml_session")
            if not raw:
                return None
            token = raw.value
            if "." not in token:
                return None
            uid_s, sig = token.split(".", 1)
            if not uid_s.isdigit():
                return None
            if not hmac.compare_digest(sig, self._sign(int(uid_s)).split(".", 1)[1]):
                return None
            uid = int(uid_s)
            return uid if store.user(uid) else None

        def _form(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 1_000_000:
                return {}
            raw = self.rfile.read(length).decode("utf-8", "replace")
            return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

        def _query(self):
            if "?" not in self.path:
                return {}
            qs = self.path.split("?", 1)[1]
            return {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}

        def _path(self):
            return urllib.parse.urlsplit(self.path).path

        def _email(self, uid):
            row = store.user(uid)
            return row["email"] if row else None


        # ---------- GET ----------
        def do_GET(self):
            path, query = self._path(), self._query()
            uid = self._uid()
            flash = FLASH_OK.get(query.get("ok", ""))
            err = FLASH_ERR.get(query.get("err", "")) if query.get("err") else None
            if poster_fn is not None and path.startswith("/poster/") and path.endswith(".svg"):
                mid = path[len("/poster/"):-4]
                if not mid.isdigit():
                    return self._send(404, "no such poster", "text/plain; charset=utf-8")
                return self._send(200, poster_fn(mid), "image/svg+xml")
            if path == "/healthz":
                return self._send(200, json.dumps({"ok": True, "user": bool(uid)}),
                                  ctype="application/json")
            if path == "/":
                return self._send(200, pages.home(self._email(uid),
                                                  notice=flash, error=err))
            if path == "/search":
                q = (query.get("q") or "").strip()
                if not q:
                    return self._send(200, pages.home(self._email(uid), error=err))
                try:
                    results = tmdb.search(q)
                except Exception as exc:
                    return self._send(200, pages.home(self._email(uid), q,
                                                     results=[], error=_search_error(exc)), )
                return self._send(200, pages.home(self._email(uid), q, results, error=err))
            if path.startswith("/movie/"):
                return self._movie(path.rsplit("/", 1)[-1], uid, flash, err)
            if path == "/watchlist":
                if uid is None:
                    return self._redirect("/login")
                rows = store.watchlist(uid)
                return self._send(200, pages.watchlist_page(rows, self._email(uid),
                                                            notice=flash, error=err))
            if path in ("/login", "/signup"):
                if uid:
                    return self._redirect("/")
                return self._send(200, pages.auth_form(path.strip("/"), error=err))
            return self._send(404, pages.layout("Not found",
                                                "<h1>Page not found</h1>"
                                                '<p class="ov"><a href="/">Back to search</a></p>'),
                              error=None)

        def _movie(self, raw_id, uid, flash, err):
            if not raw_id.isdigit():
                return self._send(404, pages.layout("Not found", "<h1>Page not found</h1>"))
            mid = int(raw_id)
            try:
                m = tmdb.movie(mid)
            except Exception as exc:
                return self._send(404, pages.layout("Title unavailable",
                                                    "<h1>We could not load that title</h1>"
                                                    '<p class="ov">%s</p>'
                                                    '<p><a href="/">Back to search</a></p>'
                                                    % pages.esc(exc), user=self._email(uid)),
                                  error=err)
            my_row, recs = None, []
            if uid:
                my_row = next((r for r in store.watchlist(uid) if int(r["movie_id"]) == mid), None)
                try:
                    recs = store.similar_picks(uid, tmdb.recommendations(mid), limit=10)
                except Exception:
                    recs = []
            else:
                try:
                    recs = tmdb.recommendations(mid)[:10]
                except Exception:
                    recs = []
            return self._send(200, pages.movie_detail(m, my_row, recs, self._email(uid),
                                                      notice=flash, error=err))

        # ---------- POST ----------
        def do_POST(self):
            path = self._path()
            form = self._form()
            uid = self._uid()
            try:
                if path == "/signup":
                    new_id = store.signup(form.get("email", ""), form.get("password", ""))
                    return self._redirect("/?ok=signed_up", self._cookie(self._sign(new_id)))
                if path == "/login":
                    uid2 = store.login(form.get("email", ""), form.get("password", ""))
                    return self._redirect("/?ok=signed_in", self._cookie(self._sign(uid2)))
                if path == "/logout":
                    return self._redirect("/?ok=signed_out", self._cookie("", max_age=0))
                if uid is None:
                    return self._redirect("/login")
                return self._post_authed(path, form, uid)
            except AuthError as exc:
                mode = "signup" if path == "/signup" else "login"
                return self._send(400, pages.auth_form(mode, error=str(exc)))
            except _TmdbError:
                return self._redirect("/watchlist?err=invalid")
            except (NotOnWatchlist, NotWatched, StoreError) as exc:
                mid = str(form.get("movie_id", ""))
                back = "/movie/%s" % mid if mid.isdigit() else "/watchlist"
                return self._redirect("%s?err=%s" % (back, _code(str(exc))))
            except Exception as exc:
                return self._send(500, pages.layout("Error", "<h1>Something went wrong</h1>"
                                                    '<p class="ov">%s</p>' % pages.esc(exc),
                                                    user=self._email(uid)))

        def _mid(self, form):
            v = str(form.get("movie_id", ""))
            return int(v) if v.isdigit() else 0

        def _post_authed(self, path, form, uid):
            if path == "/watchlist/add":
                mid = self._mid(form)
                store.add(uid, tmdb.movie(mid))
                return self._redirect("/movie/%d?ok=added" % mid)
            if path == "/watchlist/remove":
                mid = self._mid(form)
                store.remove(uid, mid)
                return self._redirect("/watchlist?ok=removed")
            if path == "/watchlist/watched":
                mid = self._mid(form)
                on = form.get("watched", "1") == "1"
                store.set_watched(uid, mid, on)
                return self._redirect("/movie/%d?ok=%s" % (mid, "watched" if on else "unwatched"))
            if path == "/rate":
                mid = self._mid(form)
                store.rate(uid, mid, form.get("stars", ""))
                return self._redirect("/movie/%d?ok=rated" % mid)
            return self._send(404, pages.layout("Not found", "<h1>Page not found</h1>"))

    return Handler


def _search_error(exc):
    """A film fan, not a programmer, is reading this box."""
    text = str(exc)
    if isinstance(exc, TmdbConfigError):
        return "This copy has no TMDB key. Set TMDB_API_KEY and restart. (%s)" % text
    if isinstance(exc, TmdbAuthError):
        return "TMDB turned the API key down - check TMDB_API_KEY. (%s)" % text
    if isinstance(exc, TmdbNetworkError):
        return "Could not reach TMDB just now. Check the connection, then try again. (%s)" % text
    return "Search is not available right now. Try again in a moment. (%s)" % text


def _code(message):
    m = message.lower()
    if "between 1 and 5" in m or "whole number" in m:
        return "bad_rating"
    if "watchlist" in m:
        return "not_on_watchlist"
    if "watched" in m:
        return "not_watched"
    return "invalid"
