"""SQLite persistence: accounts, watchlist, ratings.

Every write goes through this module, so the invariants live here and the web
layer cannot poke the tables directly:

  * a movie must be on the watchlist before it can be marked watched;
  * only watched movies can be rated, stars are an integer 1..5;
  * re-rating overwrites instead of inserting a second row;
  * similar picks never include a movie already on that user's watchlist.
"""
import hashlib
import os
import secrets
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
    user_id INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    year TEXT,
    poster TEXT,
    tmdb_rating REAL,
    watched INTEGER NOT NULL DEFAULT 0,
    added_at REAL NOT NULL,
    PRIMARY KEY (user_id, movie_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS ratings (
    user_id INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, movie_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""


class StoreError(Exception):
    pass


class NotOnWatchlist(StoreError):
    pass


class NotWatched(StoreError):
    pass


class AuthError(StoreError):
    pass


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("utf-8"), 120_000)
    return salt, digest.hex()


class Store:
    def __init__(self, path=":memory:"):
        self.path = path
        if path not in (":memory:", ""):
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        # ThreadingHTTPServer 下同一个连接会被多个请求线程碰到，写操作必须串行，
        # 否则两个并发提交可能撞出 "database is locked"。读也一起锁，逻辑最省心。
        self._lock = threading.RLock()

    def close(self):
        self.conn.close()

    # ---------- accounts ----------
    def signup(self, email, password):
        email = (email or "").strip().lower()
        if "@" not in email or len(email) < 5:
            raise AuthError("Please enter a valid email address.")
        if len(password or "") < 8:
            raise AuthError("Password must be at least 8 characters.")
        salt, pw = hash_password(password)
        try:
            cur = self.conn.execute(
                "INSERT INTO users (email, pw_hash, salt, created_at) VALUES (?,?,?,?)",
                (email, pw, salt, time.time()))
        except sqlite3.IntegrityError:
            raise AuthError("That email is already registered. Sign in instead.")
        self.conn.commit()
        return cur.lastrowid

    def login(self, email, password):
        email = (email or "").strip().lower()
        row = self.conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            raise AuthError("No account with that email.")
        _, candidate = hash_password(password or "", row["salt"])
        if not secrets.compare_digest(candidate, row["pw_hash"]):
            raise AuthError("Wrong password.")
        return row["id"]

    def user(self, user_id):
        return self.conn.execute("SELECT id, email FROM users WHERE id = ?",
                                 (user_id,)).fetchone()

    # ---------- watchlist ----------
    def add(self, user_id, movie):
        mid = int(movie["id"])
        self.conn.execute(
            "INSERT INTO watchlist (user_id, movie_id, title, year, poster,"
            " tmdb_rating, watched, added_at) VALUES (?,?,?,?,?,?,0,?)"
            " ON CONFLICT(user_id, movie_id) DO UPDATE SET"
            " title=excluded.title, year=excluded.year,"
            " poster=excluded.poster, tmdb_rating=excluded.tmdb_rating",
            (user_id, mid, movie.get("title") or "", movie.get("year"),
             movie.get("poster"), movie.get("rating"), time.time()))
        self.conn.commit()

    def remove(self, user_id, movie_id):
        cur = self.conn.execute("DELETE FROM watchlist WHERE user_id=? AND movie_id=?",
                                (user_id, int(movie_id)))
        self.conn.execute("DELETE FROM ratings WHERE user_id=? AND movie_id=?",
                          (user_id, int(movie_id)))
        self.conn.commit()
        return cur.rowcount > 0

    def set_watched(self, user_id, movie_id, watched=True):
        """Ticking "watched" on is the precondition for rating; ticking it off clears
        the rating.

        ★ 2026-10-28 修：原实现只改 watched 标志，把评分留在库里。结果是列表页
          显示 "—（未看）" 却仍写着 "5/5"，而详情页说"没评过"——同一个用户两处
          看到两个事实。评分在这套模型里的含义是"看过之后的评价"，未看过而有评分
          是非法的组合，不能只是界面上藏起来。
        """
        cur = self.conn.execute(
            "UPDATE watchlist SET watched=? WHERE user_id=? AND movie_id=?",
            (1 if watched else 0, user_id, int(movie_id)))
        if cur.rowcount == 0:
            raise NotOnWatchlist("Add the movie to your watchlist first.")
        if not watched:
            self.conn.execute(
                "DELETE FROM ratings WHERE user_id=? AND movie_id=?",
                (user_id, int(movie_id)))
        self.conn.commit()

    def watchlist(self, user_id):
        rows = self.conn.execute(
            "SELECT w.*, r.stars FROM watchlist w LEFT JOIN ratings r"
            " ON r.user_id=w.user_id AND r.movie_id=w.movie_id"
            " WHERE w.user_id=? ORDER BY w.added_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def watchlist_ids(self, user_id):
        rows = self.conn.execute("SELECT movie_id FROM watchlist WHERE user_id=?",
                                 (user_id,)).fetchall()
        return {int(r["movie_id"]) for r in rows}

    # ---------- ratings ----------
    def rate(self, user_id, movie_id, stars):
        try:
            stars = int(stars)
        except (TypeError, ValueError):
            raise StoreError("Rating must be a whole number from 1 to 5.")
        if stars < 1 or stars > 5:
            raise StoreError("Rating must be between 1 and 5 stars.")
        row = self.conn.execute(
            "SELECT watched FROM watchlist WHERE user_id=? AND movie_id=?",
            (user_id, int(movie_id))).fetchone()
        if row is None:
            raise NotOnWatchlist("Add the movie to your watchlist first.")
        if not row["watched"]:
            raise NotWatched("Mark the movie as watched before rating it.")
        self.conn.execute(
            "INSERT INTO ratings (user_id, movie_id, stars, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(user_id, movie_id) DO UPDATE SET"
            " stars=excluded.stars, updated_at=excluded.updated_at",
            (user_id, int(movie_id), stars, time.time()))
        self.conn.commit()

    def rating_of(self, user_id, movie_id):
        row = self.conn.execute(
            "SELECT stars FROM ratings WHERE user_id=? AND movie_id=?",
            (user_id, int(movie_id))).fetchone()
        return row["stars"] if row else None

    # ---------- similar picks ----------
    def similar_picks(self, user_id, candidates, limit=10):
        """Drop anything already on this user's watchlist, cap at `limit`."""
        seen = self.watchlist_ids(user_id)
        out = []
        for c in candidates:
            mid = c.get("id")
            if mid is None or int(mid) in seen:
                continue
            seen.add(int(mid))
            out.append(c)
            if len(out) >= limit:
                break
        return out


def _locked(fn):
    """Serialize every public Store method on the connection lock."""
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


for _name in ("signup", "login", "user", "add", "remove", "set_watched",
              "watchlist", "watchlist_ids", "rate", "rating_of", "similar_picks"):
    setattr(Store, _name, _locked(getattr(Store, _name)))
