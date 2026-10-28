#!/usr/bin/env python3
"""Regenerate screenshots/ from the running app (demo mode, no network).

    python3 tools/make_screenshots.py

It starts the app on a free port with a throw-away database, drives the real
HTTP endpoints (signup -> add -> watched -> rate), saves the exact HTML the
server returned, and renders each page with headless Edge/Chrome.
Purely a documentation tool; the app itself does not use it.
"""
import hashlib
import http.cookiejar
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "screenshots")

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def wait_up(base, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def shoot(bin_path, html_path, png_path, size="1280,900"):
    cmd = [bin_path, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", "--window-size=" + size,
           "--screenshot=" + png_path, "file://" + html_path.replace("\\", "/")]
    env = dict(os.environ)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    return proc.returncode, os.path.exists(png_path)


def _cleanup(path):
    for name in os.listdir(path):
        try:
            os.remove(os.path.join(path, name))
        except OSError:
            pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def main():
    bin_path = browser()
    if not bin_path:
        print("[!] no Chrome/Edge/Chromium found; screenshots not regenerated")
        return 2
    os.makedirs(OUT, exist_ok=True)
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    tmp = tempfile.mkdtemp(prefix="ml-shots-")
    db = os.path.join(tmp, "shots.db")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "run.py"),
                            "--demo", "--port", str(port), "--db", db, "--quiet"],
                           cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if not wait_up(base):
            print("[!] server did not start")
            return 3
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def post(path, data):
            body = urllib.parse.urlencode(data).encode()
            try:
                with op.open(base + path, body, timeout=10) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()

        def get(path):
            with op.open(base + path, timeout=10) as r:
                return r.read().decode("utf-8", "replace")

        made = []
        # 1) 未登录的欢迎页（截图要在注册之前拍）
        html = get("/")
        html = html.replace('src="/poster/', 'src="%s/poster/' % base)
        local = os.path.join(tmp, "00-welcome.html")
        with open(local, "w", encoding="utf-8") as fh:
            fh.write(html)
        png = os.path.join(OUT, "00-welcome.png")
        rc, ok = shoot(bin_path, local, png, "1280,760")
        made.append(("00-welcome.png", rc, ok, os.path.getsize(png) if ok else 0))

        post("/signup", {"email": "filmfan@example.com", "password": "hunter2hunter2"})
        for mid, watched, stars in (("348", 1, 5), ("126889", 1, 3), ("157336", 0, None)):
            post("/watchlist/add", {"movie_id": mid})
            if watched:
                post("/watchlist/watched", {"movie_id": mid, "watched": "1"})
            if stars:
                post("/rate", {"movie_id": mid, "stars": str(stars)})
        post("/watchlist/add", {"movie_id": "679"})

        pages = [("01-search.html", "/search?q=alien", "1280,860"),
                 ("02-movie-detail.html", "/movie/348", "1280,1180"),
                 ("03-ratings.html", "/movie/126889", "1280,900"),
                 ("04-watchlist.html", "/watchlist", "1280,760"),
                 ("05-similar-picks.html", "/movie/679", "1280,1080")]
        for name, path, size in pages:
            html = get(path)
            html = html.replace('src="/poster/', 'src="%s/poster/' % base)
            local = os.path.join(tmp, name)
            with open(local, "w", encoding="utf-8") as fh:
                fh.write(html)
            png = os.path.join(OUT, name.replace(".html", ".png"))
            rc, ok = shoot(bin_path, local, png, size)
            made.append((os.path.basename(png), rc, ok,
                         os.path.getsize(png) if ok else 0))
        for row in made:
            print("  %-24s rc=%s ok=%s %6d bytes" % row)

        # ★ 2026-10-28 加：两张截图若字节完全相同，就是"同一张图冒充两个流程"。
        # 第一版 02 与 05 都是 /movie/348 同尺寸，sha256 一致，等于证据重复。
        digests = {}
        for name, _rc, ok, _size in made:
            if not ok:
                continue
            path = os.path.join(OUT, name)
            with open(path, "rb") as fh:
                digests[name] = hashlib.sha256(fh.read()).hexdigest()
        dupes = {}
        for name, dg in digests.items():
            dupes.setdefault(dg, []).append(name)
        clash = [v for v in dupes.values() if len(v) > 1]
        if clash:
            for group in clash:
                print("[x] identical screenshots: %s" % " == ".join(group))
            return 5
        print("  distinct: %d/%d unique images" % (len(digests), len(made)))
        return 0 if all(r[2] for r in made) else 4
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()
        _cleanup(tmp)


if __name__ == "__main__":
    raise SystemExit(main())
