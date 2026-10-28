"""HTML rendering. Plain string templates - no template engine, no extra deps."""
import html

CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0e1116;color:#e8eaed;
 font:15px/1.6 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:#8ab4f8;text-decoration:none}
header{display:flex;align-items:center;gap:18px;padding:14px 22px;
 background:#151a21;border-bottom:1px solid #232b36;position:sticky;top:0}
header .brand{font-weight:700;font-size:17px;color:#fff;letter-spacing:.2px}
header .sp{gap:12px;margin-left:auto;display:flex;align-items:center;font-size:14px}
main{max-width:1080px;margin:0 auto;padding:26px 22px 60px}
h1{font-size:22px;margin:0 0 16px}
h2{font-size:17px;margin:28px 0 12px}
form.search{display:flex;gap:8px;margin:0 0 22px}
input[type=text],input[type=email],input[type=password]{flex:1;background:#0b0f14;
 color:#e8eaed;border:1px solid #2a3542;border-radius:8px;padding:10px 12px;font-size:15px}
button{background:#1a73e8;color:#fff;border:0;border-radius:8px;padding:10px 16px;
 font-size:14px;font-weight:600;cursor:pointer}
button.ghost{background:#212a36;color:#c7d0da;border:1px solid #2f3a49}
button:disabled{opacity:.5;cursor:default}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:16px}
.card{background:#151a21;border:1px solid #232b36;border-radius:12px;overflow:hidden;
 display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:2/3;object-fit:cover;background:#0b0f14;display:block}
.card .body{padding:9px 10px 11px;display:flex;flex-direction:column;gap:5px;flex:1}
.card .t{font-size:13px;font-weight:600;line-height:1.35}
.card .m{font-size:12px;color:#93a0af}
.poster-none{width:100%;aspect-ratio:2/3;display:flex;align-items:center;
 justify-content:center;background:#0b0f14;color:#4a5666;font-size:12px}
.row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.badge{display:inline-block;background:#1f2a38;color:#9fd0ff;border-radius:999px;
 padding:1px 9px;font-size:12px;font-weight:600}
.stars{display:flex;gap:3px}
.stars button{background:none;border:0;padding:0 1px;font-size:19px;line-height:1;
 color:#3a4553;cursor:pointer}
.stars button.on{color:#f5c451}
.notice{background:#1d2a1f;border:1px solid #2e4a33;color:#b7f0c2;
 padding:10px 13px;border-radius:9px;margin:0 0 18px;font-size:14px}
.error{background:#2a1d1f;border:1px solid #4a2e33;color:#ffbdc4;
 padding:10px 13px;border-radius:9px;margin:0 0 18px;font-size:14px}
.empty{color:#8b97a5;padding:26px 0}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #232b36}
th{color:#8b97a5;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.hero{display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap}
.hero img{width:210px;border-radius:12px;background:#0b0f14}
.hero .info{flex:1;min-width:260px}
.ov{color:#a9b4c0;font-size:14px;margin:12px 0}
code{background:#0b0f14;border:1px solid #2a3542;border-radius:5px;padding:1px 6px;font-size:13px}
.help{color:#8b97a5;font-size:13px;margin-top:8px}
"""

STAR = {1: "\u2605", 0: "\u2606"}


def esc(text):
    return html.escape("" if text is None else str(text))


def layout(title, body, user=None, notice=None, error=None):
    nav = ('<div class="sp">'
           '<a href="/watchlist">My watchlist</a>'
           '<span>%s</span>'
           '<form method="post" action="/logout" style="display:inline">'
           '<button class="ghost" type="submit">Sign out</button></form>'
           '</div>' % esc(user)) if user else (
           '<div class="sp"><a href="/login">Sign in</a>'
           '<a href="/signup">Create account</a></div>')
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>%s - Movie Lovers</title><style>%s</style></head><body>' % (esc(title), CSS),
             '<header><a class="brand" href="/">\U0001f3ac Movie Lovers</a>', nav, '</header><main>']
    if notice:
        parts.append('<div class="notice">%s</div>' % esc(notice))
    if error:
        parts.append('<div class="error">%s</div>' % esc(error))
    parts.append(body)
    parts.append('</main></body></html>')
    return "".join(parts)


def poster_block(m):
    if m.get("poster"):
        return '<img src="%s" alt="%s poster" loading="lazy">' % (esc(m["poster"]), esc(m["title"]))
    return '<div class="poster-none">no poster</div>'


def movie_card(m):
    meta = []
    if m.get("year"):
        meta.append(esc(m["year"]))
    if m.get("rating") is not None:
        meta.append("\u2605 " + esc(m["rating"]))
    return ('<div class="card"><a href="/movie/%d">%s</a><div class="body">'
            '<div class="t"><a href="/movie/%d">%s</a></div>'
            '<div class="m">%s</div></div></div>'
            % (int(m["id"]), poster_block(m), int(m["id"]), esc(m["title"]),
               " \u00b7 ".join(meta)))


def home(user, query="", results=None, notice=None, error=None):
    form = ('<form class="search" method="get" action="/search">'
            '<input type="text" name="q" placeholder="Search a film title, e.g. Alien" '
            'value="%s" aria-label="Search a film title" autofocus>'
            '<button type="submit">Search</button></form>' % esc(query))
    if not user and results is not None:
        grid = ('<h2>%d result%s for \u201c%s\u201d</h2><div class="grid">%s</div>'
                '<p class="help">Create a free account to add any of these to a watchlist '
                'and rate them.</p>'
                % (len(results), "" if len(results) == 1 else "s", esc(query),
                   "".join(movie_card(m) for m in results))) if results else (
                '<div class="empty">No films matched <b>%s</b>. Try a shorter title.</div>'
                % esc(query))
        body = (form + grid +
                '<div class="row" style="margin-top:22px">'
                '<a href="/signup"><button>Create a free account</button></a>'
                '<a href="/login"><button class="ghost">I already have one</button></a></div>')
        return layout("Search", body, notice=notice, error=error)
    if not user:
        body = ('<h1>Find your next favourite film</h1>'
                '<p class="ov">Search any title, keep a watchlist, tick off what you have '
                'watched, rate it 1\u20135 stars, and get similar picks that never repeat '
                'something already on your list.</p>'
                '<div class="row"><a href="/signup"><button>Create a free account</button></a>'
                '<a href="/login"><button class="ghost">I already have one</button></a></div>'
                '<p class="help">You need an account to keep a watchlist \u2014 '
                'you can still search without one.</p>')
        return layout("Welcome", body + form, notice=notice, error=error)
    body = ['<h1>Search</h1>', form]
    if results is not None:
        if query and not results:
            body.append('<div class="empty">No films matched <b>%s</b>. '
                        'Try a shorter title.</div>' % esc(query))
        elif results:
            body.append('<h2>%d result%s for \u201c%s\u201d</h2>'
                        % (len(results), "" if len(results) == 1 else "s", esc(query)))
            body.append('<div class="grid">%s</div>' % "".join(movie_card(m) for m in results))
    return layout("Search", "".join(body), user=user, notice=notice, error=error)


def auth_form(mode, error=None):
    if mode == "login":
        body = ('<h1>Sign in</h1><form method="post" action="/login">'
                '<p><input type="email" name="email" placeholder="Email" required></p>'
                '<p><input type="password" name="password" placeholder="Password" required></p>'
                '<button type="submit">Sign in</button></form>'
                '<p class="help">No account yet? <a href="/signup">Create one</a>.</p>')
        return layout("Sign in", body, error=error)
    body = ('<h1>Create your account</h1><form method="post" action="/signup">'
            '<p><input type="email" name="email" placeholder="Email" required></p>'
            '<p><input type="password" name="password" placeholder="Password '
            '(8+ characters)" required></p>'
            '<button type="submit">Create account</button></form>'
            '<p class="help">Already registered? <a href="/login">Sign in</a>.</p>')
    return layout("Create account", body, error=error)


def stars_row(movie_id, mine):
    out = ['<div class="stars" role="group" aria-label="Your rating">']
    for n in range(1, 6):
        on = " on" if mine and n <= mine else ""
        out.append('<form method="post" action="/rate" style="display:inline">'
                   '<input type="hidden" name="movie_id" value="%d">'
                   '<input type="hidden" name="stars" value="%d">'
                   '<button class="%s" type="submit" title="%d star%s" %s>%s</button>'
                   '</form>'
                   % (movie_id, n, on.strip(),
                      n, "" if n == 1 else "s",
                      "" if (mine and mine >= n) else "",
                      STAR[1] if (mine and n <= mine) else STAR[0]))
    out.append('</div>')
    return "".join(out)


def movie_detail(m, my_row, recs, user, notice=None, error=None):
    meta = []
    if m.get("year"):
        meta.append('<span class="badge">%s</span>' % esc(m["year"]))
    if m.get("rating") is not None:
        meta.append('<span class="badge">TMDB \u2605 %s</span>' % esc(m["rating"]))
    actions = []
    if my_row is None:
        actions.append('<form method="post" action="/watchlist/add" style="display:inline">'
                       '<input type="hidden" name="movie_id" value="%d">'
                       '<button type="submit">Add to watchlist</button></form>' % int(m["id"]))
    else:
        watched = bool(my_row.get("watched"))
        actions.append('<form method="post" action="/watchlist/watched" style="display:inline">'
                       '<input type="hidden" name="movie_id" value="%d">'
                       '<input type="hidden" name="watched" value="%d">'
                       '<button type="submit">%s</button></form>'
                       % (int(m["id"]), 0 if watched else 1,
                          "Mark as not watched" if watched else "Mark as watched"))
        actions.append('<form method="post" action="/watchlist/remove" style="display:inline">'
                       '<input type="hidden" name="movie_id" value="%d">'
                       '<button class="ghost" type="submit">Remove from watchlist</button>'
                       '</form>' % int(m["id"]))
    rating_block = ""
    if my_row is not None:
        mine = my_row.get("stars")
        if my_row.get("watched"):
            rating_block = ('<h2>Your rating</h2>'
                            '<div class="row">%s<span class="m">%s</span></div>'
                            % (stars_row(int(m["id"]), mine),
                               ("You rated it %d/5" % mine) if mine else "Not rated yet"))
        else:
            rating_block = ('<h2>Your rating</h2>'
                            '<p class="help">Mark this film as watched to rate it.</p>')
    body = ('<div class="hero">%s<div class="info"><h1>%s</h1>'
            '<div class="row">%s</div><p class="ov">%s</p>'
            '<div class="row">%s</div>%s</div></div>'
            % (poster_block(m), esc(m["title"]), "".join(meta),
               esc(m.get("overview") or "No synopsis available."),
               "".join(actions), rating_block))
    if recs:
        body += ('<h2>Similar picks</h2><p class="help">Up to 10 titles TMDB recommends, '
                 'excluding anything already on your watchlist.</p>'
                 '<div class="grid">%s</div>' % "".join(movie_card(r) for r in recs))
    else:
        body += ('<h2>Similar picks</h2><div class="empty">Nothing to suggest \u2014 '
                 'either TMDB has no recommendations for this title, or everything it '
                 'suggests is already on your watchlist.</div>')
    return layout(m["title"], body, user=user, notice=notice, error=error)


def watchlist_page(rows, user, notice=None, error=None):
    if not rows:
        body = ('<h1>My watchlist</h1><div class="empty">Nothing here yet. '
                '<a href="/">Search for a film</a> and add it.</div>')
        return layout("My watchlist", body, user=user, notice=notice, error=error)
    trs = []
    for r in rows:
        watched = '<span class="badge">watched</span>' if r["watched"] else "&mdash;"
        stars = ("%d/5" % r["stars"]) if r.get("stars") else "&mdash;"
        trs.append(
            '<tr><td><a href="/movie/%d">%s</a></td><td>%s</td><td>%s</td><td>%s</td>'
            '<td><form method="post" action="/watchlist/watched" style="display:inline">'
            '<input type="hidden" name="movie_id" value="%d">'
            '<input type="hidden" name="watched" value="%d">'
            '<button class="ghost" type="submit">%s</button></form> '
            '<form method="post" action="/watchlist/remove" style="display:inline">'
            '<input type="hidden" name="movie_id" value="%d">'
            '<button class="ghost" type="submit">Remove</button></form></td></tr>'
            % (int(r["movie_id"]), esc(r["title"]), esc(r.get("year")) or "&mdash;",
               watched, stars, int(r["movie_id"]),
               0 if r["watched"] else 1,
               "Un-watch" if r["watched"] else "Mark watched", int(r["movie_id"])))
    body = ('<h1>My watchlist</h1><p class="help">%d title%s saved.</p>'
            '<table><thead><tr><th>Title</th><th>Year</th><th>Watched</th>'
            '<th>Your rating</th><th>Actions</th></tr></thead><tbody>%s</tbody></table>'
            % (len(rows), "" if len(rows) == 1 else "s", "".join(trs)))
    return layout("My watchlist", body, user=user, notice=notice, error=error)
