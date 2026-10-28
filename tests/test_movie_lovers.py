"""Test suite. One command: python3 test_all.py

No network, no TMDB key: the TMDB transport is faked and every test uses a
throw-away SQLite file. This is what runs in CI and what a reviewer runs.
"""
import http.cookiejar
import json
import os
import re
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app import tmdb as tmdb_mod
from app.server import make_server
from app.store import AuthError, NotOnWatchlist, NotWatched, Store, StoreError
from run import FixtureTransport, poster_svg


def movie(mid, title="T", year="2000", rating=7.0):
    return {"id": mid, "title": title, "year": year, "rating": rating,
            "poster": None, "overview": ""}


class StoreAccounts(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

    def test_signup_then_login(self):
        uid = self.s.signup("a@example.com", "hunter2hunter2")
        self.assertEqual(self.s.login("A@Example.com", "hunter2hunter2"), uid)

    def test_duplicate_email_is_rejected(self):
        self.s.signup("a@example.com", "hunter2hunter2")
        with self.assertRaises(AuthError):
            self.s.signup("a@example.com", "another-pass")

    def test_wrong_password_is_rejected(self):
        self.s.signup("a@example.com", "hunter2hunter2")
        with self.assertRaises(AuthError):
            self.s.login("a@example.com", "nope-nope-nope")

    def test_short_password_is_rejected(self):
        with self.assertRaises(AuthError):
            self.s.signup("a@example.com", "short")

    def test_email_is_normalised(self):
        self.s.signup("  Mixed@Case.COM ", "hunter2hunter2")
        self.assertTrue(self.s.login("mixed@case.com", "hunter2hunter2"))


class StoreWatchlist(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.uid = self.s.signup("w@example.com", "hunter2hunter2")

    def test_add_and_list(self):
        self.s.add(self.uid, movie(1, "Alien", "1979", 8.2))
        rows = self.s.watchlist(self.uid)
        self.assertEqual([r["movie_id"] for r in rows], [1])
        self.assertEqual(rows[0]["title"], "Alien")
        self.assertEqual(rows[0]["watched"], 0)

    def test_add_twice_does_not_duplicate(self):
        self.s.add(self.uid, movie(1))
        self.s.add(self.uid, movie(1))
        self.assertEqual(len(self.s.watchlist(self.uid)), 1)

    def test_remove(self):
        self.s.add(self.uid, movie(1))
        self.assertTrue(self.s.remove(self.uid, 1))
        self.assertEqual(self.s.watchlist(self.uid), [])

    def test_remove_unknown_is_false_not_error(self):
        self.assertFalse(self.s.remove(self.uid, 999))

    def test_mark_watched_requires_watchlist_entry(self):
        with self.assertRaises(NotOnWatchlist):
            self.s.set_watched(self.uid, 42, True)

    def test_mark_watched_toggles(self):
        self.s.add(self.uid, movie(1))
        self.s.set_watched(self.uid, 1, True)
        self.assertEqual(self.s.watchlist(self.uid)[0]["watched"], 1)
        self.s.set_watched(self.uid, 1, False)
        self.assertEqual(self.s.watchlist(self.uid)[0]["watched"], 0)

    def test_unwatch_drops_rating(self):
        """Ticking watched off must clear the rating: "unwatched but 5/5" is a
        contradiction a reviewer will find in ten seconds."""
        self.s.add(self.uid, movie(1))
        self.s.set_watched(self.uid, 1, True)
        self.s.rate(self.uid, 1, 5)
        self.s.set_watched(self.uid, 1, False)
        self.assertIsNone(self.s.rating_of(self.uid, 1))
        row = self.s.watchlist(self.uid)[0]
        self.assertEqual(row["watched"], 0)
        self.assertIsNone(row["stars"])

    def test_rewatching_starts_from_no_rating(self):
        self.s.add(self.uid, movie(1))
        self.s.set_watched(self.uid, 1, True)
        self.s.rate(self.uid, 1, 3)
        self.s.set_watched(self.uid, 1, False)
        self.s.set_watched(self.uid, 1, True)
        self.assertIsNone(self.s.rating_of(self.uid, 1))

    def test_remove_also_drops_rating(self):
        self.s.add(self.uid, movie(1))
        self.s.set_watched(self.uid, 1, True)
        self.s.rate(self.uid, 1, 4)
        self.s.remove(self.uid, 1)
        self.s.add(self.uid, movie(1))
        self.assertIsNone(self.s.rating_of(self.uid, 1))

    def test_two_users_are_isolated(self):
        other = self.s.signup("o@example.com", "hunter2hunter2")
        self.s.add(self.uid, movie(1))
        self.assertEqual(self.s.watchlist(other), [])


class StoreRatings(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.uid = self.s.signup("r@example.com", "hunter2hunter2")
        self.s.add(self.uid, movie(1))
        self.s.set_watched(self.uid, 1, True)

    def test_rate_all_five_values(self):
        for stars in range(1, 6):
            self.s.rate(self.uid, 1, stars)
            self.assertEqual(self.s.rating_of(self.uid, 1), stars)

    def test_rating_is_overwritten_not_appended(self):
        self.s.rate(self.uid, 1, 2)
        self.s.rate(self.uid, 1, 5)
        rows = self.s.conn.execute("SELECT COUNT(*) c FROM ratings").fetchone()
        self.assertEqual(rows["c"], 1)
        self.assertEqual(self.s.rating_of(self.uid, 1), 5)

    def test_zero_and_six_are_rejected(self):
        for bad in (0, 6, -1, 99):
            with self.assertRaises(StoreError):
                self.s.rate(self.uid, 1, bad)

    def test_text_and_empty_are_rejected(self):
        for bad in ("abc", "", None):
            with self.assertRaises(StoreError):
                self.s.rate(self.uid, 1, bad)

    def test_numeric_string_is_accepted(self):
        self.s.rate(self.uid, 1, "4")
        self.assertEqual(self.s.rating_of(self.uid, 1), 4)

    def test_cannot_rate_before_watched(self):
        second = self.s.signup("r2@example.com", "hunter2hunter2")
        self.s.add(second, movie(2))
        with self.assertRaises(NotWatched):
            self.s.rate(second, 2, 4)

    def test_cannot_rate_off_watchlist(self):
        with self.assertRaises(NotOnWatchlist):
            self.s.rate(self.uid, 777, 3)

    def test_db_check_constraint_is_the_last_wall(self):
        """Even a direct INSERT bypassing rate() is refused by the schema."""
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.conn.execute(
                "INSERT INTO ratings (user_id, movie_id, stars, updated_at)"
                " VALUES (?,?,?,0)", (self.uid, 1, 9))


class SimilarPicks(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.uid = self.s.signup("p@example.com", "hunter2hunter2")

    def test_excludes_watchlisted_titles(self):
        self.s.add(self.uid, movie(2))
        cands = [movie(1), movie(2), movie(3)]
        got = [m["id"] for m in self.s.similar_picks(self.uid, cands)]
        self.assertEqual(got, [1, 3])

    def test_caps_at_ten(self):
        cands = [movie(i) for i in range(1, 26)]
        self.assertEqual(len(self.s.similar_picks(self.uid, cands)), 10)

    def test_cap_applies_after_filtering(self):
        for i in range(1, 6):
            self.s.add(self.uid, movie(i))
        cands = [movie(i) for i in range(1, 26)]
        got = [m["id"] for m in self.s.similar_picks(self.uid, cands)]
        self.assertEqual(got, list(range(6, 16)))

    def test_duplicates_in_feed_collapse(self):
        cands = [movie(1), movie(1), movie(2)]
        got = [m["id"] for m in self.s.similar_picks(self.uid, cands)]
        self.assertEqual(got, [1, 2])

    def test_empty_watchlist_returns_everything_up_to_cap(self):
        cands = [movie(i) for i in range(1, 4)]
        self.assertEqual(len(self.s.similar_picks(self.uid, cands)), 3)

    def test_no_candidates(self):
        self.assertEqual(self.s.similar_picks(self.uid, []), [])


class TmdbClientBehaviour(unittest.TestCase):
    class Fake:
        def __init__(self, script):
            self.script = list(script)
            self.calls = 0

        def get(self, url, params, timeout=None):
            self.calls += 1
            return self.script.pop(0) if self.script else (500, None)

    def test_missing_key_raises_config_error(self):
        c = tmdb_mod.TmdbClient(api_key="")
        with self.assertRaises(tmdb_mod.TmdbConfigError):
            c.search("alien")

    def test_401_raises_auth_error(self):
        c = tmdb_mod.TmdbClient(api_key="bad", transport=self.Fake([(401, None)]))
        with self.assertRaises(tmdb_mod.TmdbAuthError):
            c.search("alien")

    def test_429_is_retried_then_succeeds(self):
        fake = self.Fake([(429, None), (200, {"results": [
            {"id": 348, "title": "Alien", "release_date": "1979-05-25",
             "vote_average": 8.245, "poster_path": "/x.jpg"}]})])
        c = tmdb_mod.TmdbClient(api_key="k", transport=fake, sleep=lambda s: None)
        got = c.search("alien")
        self.assertEqual(fake.calls, 2)
        self.assertEqual(got[0]["year"], "1979")
        self.assertEqual(got[0]["rating"], 8.2)
        self.assertTrue(got[0]["poster"].startswith("https://image.tmdb.org/t/p/w342/"))

    def test_retries_are_bounded(self):
        fake = self.Fake([(500, None)] * 10)
        c = tmdb_mod.TmdbClient(api_key="k", transport=fake, retries=2,
                                sleep=lambda s: None)
        with self.assertRaises(tmdb_mod.TmdbError):
            c.search("alien")
        self.assertEqual(fake.calls, 3)

    def test_blank_query_does_not_hit_network(self):
        fake = self.Fake([])
        c = tmdb_mod.TmdbClient(api_key="k", transport=fake)
        self.assertEqual(c.search("   "), [])
        self.assertEqual(fake.calls, 0)

    def test_malformed_records_are_dropped(self):
        fake = self.Fake([(200, {"results": [
            {"id": "not-an-int", "title": "bad"},
            {"title": "no id"},
            {"id": 7, "title": "Good", "release_date": "", "vote_average": None}]})])
        c = tmdb_mod.TmdbClient(api_key="k", transport=fake)
        got = c.search("x")
        self.assertEqual([m["id"] for m in got], [7])
        self.assertIsNone(got[0]["year"])
        self.assertIsNone(got[0]["rating"])


class HttpFlows(unittest.TestCase):
    """End-to-end over real HTTP: the acceptance flows a reviewer will click."""

    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.tmdb = tmdb_mod.TmdbClient(api_key="demo", transport=FixtureTransport())
        cls.httpd = make_server(cls.store, cls.tmdb, "127.0.0.1", 0,
                                poster_fn=lambda mid: poster_svg(mid, "x"))
        cls.httpd.quiet = True
        cls.port = cls.httpd.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def client(self):
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(self, op, path):
        with op.open(self.base + path, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")

    def post(self, op, path, data):
        """Returns (status, body). A 4xx is a normal outcome here, not an error."""
        body = urllib.parse.urlencode(data).encode()
        try:
            with op.open(self.base + path, body, timeout=10) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def test_10_bad_movie_id_is_a_message_not_a_crash(self):
        op = self.client()
        self.post(op, "/signup", {"email": "u10@example.com", "password": "secret123"})
        for bad in ("329", "abc", "", "-1"):
            status, body = self.post(op, "/watchlist/add", {"movie_id": bad})
            self.assertEqual(status, 200, bad)
            self.assertIn("could not be completed", body, bad)

    def test_01_health(self):
        status, body = self.get(self.client(), "/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_02_search_without_account_works(self):
        status, body = self.get(self.client(), "/search?q=alien")
        self.assertEqual(status, 200)
        self.assertIn("Alien", body)
        self.assertIn("/movie/348", body)

    def test_03_full_flow(self):
        op = self.client()
        status, _ = self.post(op, "/signup", {"email": "flow@example.com",
                                             "password": "hunter2hunter2"})
        self.assertEqual(status, 200)          # 303 followed -> landing
        self.post(op, "/watchlist/add", {"movie_id": "348"})
        _, page = self.get(op, "/watchlist")
        self.assertIn("Alien", page)
        self.assertIn("Remove", page)

        # rating before watched must be refused, and must not create a rating
        self.post(op, "/rate", {"movie_id": "348", "stars": "5"})
        _, page = self.get(op, "/movie/348")
        self.assertNotIn("You rated it 5/5", page)

        self.post(op, "/watchlist/watched", {"movie_id": "348", "watched": "1"})
        self.post(op, "/rate", {"movie_id": "348", "stars": "5"})
        _, page = self.get(op, "/movie/348")
        self.assertIn("You rated it 5/5", page)

        # change the rating
        self.post(op, "/rate", {"movie_id": "348", "stars": "2"})
        _, page = self.get(op, "/watchlist")
        self.assertIn("2/5", page)

    def test_04_similar_picks_never_contain_watchlisted(self):
        op = self.client()
        self.post(op, "/signup", {"email": "sim@example.com",
                                  "password": "hunter2hunter2"})
        self.post(op, "/watchlist/add", {"movie_id": "679"})
        _, page = self.get(op, "/movie/348")
        self.assertIn("Similar picks", page)
        self.assertIn("/movie/8077", page)        # recommended, not watched
        self.assertNotIn("/movie/679", page.split("Similar picks")[1])

    def test_05_watchlist_is_per_user(self):
        a, b = self.client(), self.client()
        self.post(a, "/signup", {"email": "ua@example.com", "password": "hunter2hunter2"})
        self.post(b, "/signup", {"email": "ub@example.com", "password": "hunter2hunter2"})
        self.post(a, "/watchlist/add", {"movie_id": "603"})
        _, page_b = self.get(b, "/watchlist")
        self.assertNotIn("The Matrix", page_b)

    def test_06_wrong_password_shows_error(self):
        op = self.client()
        self.post(op, "/signup", {"email": "pw@example.com", "password": "hunter2hunter2"})
        status, page = self.post(self.client(), "/login",
                                 {"email": "pw@example.com", "password": "wrong-pass"})
        self.assertEqual(status, 400)
        self.assertIn("Wrong password", page)

    def test_07_demo_poster_route(self):
        status, body = self.get(self.client(), "/poster/348.svg")
        self.assertEqual(status, 200)
        self.assertIn("<svg", body)

    def test_08_session_survives_server_restart(self):
        """The signing secret is on disk, so a restart must not log everyone out."""
        import tempfile
        from app.server import session_secret
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "x.db")
            first = session_secret(db)
            second = session_secret(db)
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 32)

    def test_09_logged_out_redirect_keeps_watchlist_private(self):
        op = self.client()
        status, body = self.get(op, "/watchlist")
        self.assertEqual(status, 200)
        self.assertIn("Sign in", body)

class Concurrency(unittest.TestCase):
    """The HTTP server is threaded; the store must not corrupt under parallel writes."""

    def test_parallel_ratings_keep_one_row_per_movie(self):
        import threading as th
        s = Store(":memory:")
        uid = s.signup("c@example.com", "hunter2hunter2")
        for mid in range(1, 6):
            s.add(uid, movie(mid))
            s.set_watched(uid, mid, True)
        errors = []

        def worker(n):
            try:
                for _ in range(40):
                    s.rate(uid, (n % 5) + 1, (n % 5) + 1)
            except Exception as exc:          # noqa: BLE001 - we want to see it
                errors.append(exc)

        threads = [th.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        rows = s.conn.execute("SELECT COUNT(*) c FROM ratings").fetchone()
        self.assertEqual(rows["c"], 5)


class ErrorFeedback(unittest.TestCase):
    """Every rejection must come back as a readable message, never silently."""

    def setUp(self):
        from app.server import _code
        self.code = _code

    def test_rating_bounds_map_to_bad_rating(self):
        self.assertEqual(self.code("Rating must be between 1 and 5 stars."), "bad_rating")
        self.assertEqual(self.code("Rating must be a whole number from 1 to 5."),
                         "bad_rating")

    def test_watchlist_and_watched_map(self):
        self.assertEqual(self.code("Add the movie to your watchlist first."),
                         "not_on_watchlist")
        self.assertEqual(self.code("Mark the movie as watched before rating it."),
                         "not_watched")

    def test_every_code_has_a_message(self):
        from app.server import FLASH_ERR, FLASH_OK
        for code in ("not_on_watchlist", "not_watched", "bad_rating", "invalid"):
            self.assertIn(code, FLASH_ERR)
            self.assertTrue(FLASH_ERR[code])
        for code in ("added", "removed", "watched", "unwatched", "rated"):
            self.assertIn(code, FLASH_OK)

class DocConsistency(unittest.TestCase):
    """The brief's last line: every command and screen the docs describe exists."""

    def test_the_three_documents_are_there(self):
        for name in ("README.md", "USER_GUIDE.md", "SETUP.md"):
            self.assertTrue(os.path.getsize(os.path.join(ROOT, name)) > 500, name)

    def test_every_screenshot_in_the_guide_exists(self):
        guide = open(os.path.join(ROOT, "USER_GUIDE.md"), encoding="utf-8").read()
        refs = re.findall(r"screenshots/([\w.-]+\.png)", guide)
        self.assertGreaterEqual(len(refs), 5)
        for name in refs:
            self.assertTrue(os.path.exists(os.path.join(ROOT, "screenshots", name)), name)

    def test_every_flag_in_setup_exists_in_run_py(self):
        setup = open(os.path.join(ROOT, "SETUP.md"), encoding="utf-8").read()
        runpy = open(os.path.join(ROOT, "run.py"), encoding="utf-8").read()
        used = set(re.findall(r"--[a-z]+", setup)) - {"--version"}
        missing = sorted(f for f in used if '"%s"' % f not in runpy)
        self.assertEqual(missing, [])


class FriendlyErrors(unittest.TestCase):
    """Search failures are read by a film fan, not a programmer."""

    def msg(self, exc):
        from app.server import _search_error
        return _search_error(exc)

    def test_no_key_tells_you_which_variable(self):
        m = self.msg(tmdb_mod.TmdbConfigError("TMDB_API_KEY is not set"))
        self.assertIn("TMDB_API_KEY", m)
        self.assertIn("restart", m)

    def test_bad_key_says_check_the_key(self):
        self.assertIn("check TMDB_API_KEY", self.msg(tmdb_mod.TmdbAuthError("HTTP 401")))

    def test_network_says_try_again_in_plain_words(self):
        m = self.msg(tmdb_mod.TmdbNetworkError("urlopen error timed out"))
        self.assertIn("try again", m)
        self.assertNotIn("Traceback", m)

    def test_unknown_does_not_leak_a_stack_trace(self):
        m = self.msg(ValueError("boom"))
        self.assertIn("not available right now", m)


def main():
    """Discover every TestCase in this module, so a new class cannot be forgotten."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    cases = [(name, obj) for name, obj in sorted(globals().items())
             if isinstance(obj, type) and issubclass(obj, unittest.TestCase)
             and obj is not unittest.TestCase]
    if not cases:
        raise SystemExit("no test cases found")
    for _name, case in cases:
        suite.addTests(loader.loadTestsFromTestCase(case))
    print("test classes: %s" % ", ".join(n for n, _ in cases))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
