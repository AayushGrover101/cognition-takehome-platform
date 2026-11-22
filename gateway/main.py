"""The gateway: sign-in, the portal, and serving app files to people allowed to open them."""
import html
from pathlib import Path
from urllib.parse import quote, urlsplit

from starlette.applications import Starlette
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import audit, config, connectors, switches

WEB = Path(__file__).parent / "web"
STATIC_TYPES = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".ico", ".woff2"}
COOKIE = "gw_user"


# ---------- sign-in (stand-in for company single sign-on) ----------

def current_user(request):
    return config.users().get(request.cookies.get(COOKIE, ""))


def label(role):
    return config.ROLES.get(role, role)


def is_admin(user):
    return user["role"] in config.admin_roles()


def admin_tag(user):
    return '<span class="tag">Admin</span>' if is_admin(user) else ""


def page(name, status=200, **values):
    return HTMLResponse(page_fragment(name, **values), status_code=status)


def initials(text):
    return "".join(word[0] for word in text.split()[:2]).upper()


def notice(title, lines, status):
    items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    return page("notice.html", status, title=html.escape(title), items=items, code=str(status))


def safe_next(value):
    ok = value and value.startswith("/") and not value.startswith("//") and "\\" not in value
    return value if ok and all(ord(ch) >= 32 for ch in value) else "/"


async def signin(request):
    if request.method == "POST":
        form = await request.form()
        user_id, nxt = form.get("user", ""), safe_next(form.get("next", "/"))
        if user_id not in config.users():
            return RedirectResponse("/signin", status_code=303)
        response = RedirectResponse(nxt, status_code=303)
        response.set_cookie(COOKIE, user_id, httponly=True, samesite="lax")
        return response
    nxt = safe_next(request.query_params.get("next", "/"))
    me = current_user(request)
    current = me["id"] if me else ""
    options = "".join(
        f'<option value="{html.escape(u["id"])}"{" selected" if u["id"] == current else ""}>'
        f'{html.escape(u["name"])} — {html.escape(label(u["role"]))}{" · Admin" if is_admin(u) else ""}</option>'
        for u in config.users().values()
    )
    target = config.load_apps().get(nxt.split("/")[2]) if nxt.startswith("/apps/") and nxt.count("/") >= 2 else None
    sub = f"Continue to {target['title']} with your company account." if target else "Use your company account to continue."
    return page("signin.html", options=options, none_selected="" if me else " selected",
                next=html.escape(nxt, quote=True), sub=html.escape(sub))


def can_open(user, app):
    return not app["problems"] and user["role"] in app["access"]


async def portal(request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/signin", status_code=303)
    apps = [app for app in config.load_apps().values() if can_open(user, app)]
    off = switches.off("app")
    arrow = ('<svg class="go" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" '
             'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    cards = "".join(
        (f'<div class="app off" aria-disabled="true">' if app["name"] in off else f'<a class="app" href="/apps/{html.escape(app["name"])}/">')
        + f'<span class="icon">{html.escape(initials(app["title"]))}</span>'
        f'<span class="text"><div class="title">{html.escape(app["title"])}</div>'
        f'<div class="desc">{html.escape(str(app.get("description", "")))}</div></span>'
        + ('<span class="tag">Turned off</span></div>' if app["name"] in off else f'{arrow}</a>')
        for app in apps
    )
    cards = f'<div class="apps">{cards}</div>' if apps else (
        '<div class="empty"><strong>No apps yet</strong>Nothing is available for your role. '
        'Ask your team lead if you expected to see an app here.</div>')
    count = f'{len(apps)} app{"" if len(apps) == 1 else "s"}'
    admin = '<a class="btn ghost" href="/admin">Admin</a><span class="divider"></span>' if is_admin(user) else ""
    return page("portal.html", admin=admin, tag=admin_tag(user), cards=cards, count=count, first=html.escape(user["name"].split()[0]), initials=html.escape(initials(user["name"])),
                user=html.escape(user["name"]), role=html.escape(label(user["role"])))


async def signout(request):
    """GET too, so app pages (which can't post forms) can link here. ?next= is where the next person lands."""
    nxt = safe_next(request.query_params.get("next", "/"))
    response = RedirectResponse("/signin" if nxt == "/" else f"/signin?next={quote(nxt, safe='')}", status_code=303)
    response.delete_cookie(COOKIE)
    return response


def app_csp():
    """Browser lockdown: load files and send requests only to this gateway. Which app's API a page may
    call is checked on the server (from_own_page), so it holds behind any proxy."""
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
        "connect-src 'self'; "
        "form-action 'none'; base-uri 'none'; frame-src 'none'; frame-ancestors 'none'; object-src 'none'; "
        "sandbox allow-scripts allow-same-origin allow-downloads allow-modals; "
        "report-uri /csp-report"
    )


def static_file(root, rel):
    root = root.resolve()
    target = (root / rel).resolve()
    if root not in target.parents or not target.is_file() or target.suffix.lower() not in STATIC_TYPES:
        return None
    return target


async def serve_app(request):
    name, rel = request.path_params["app"], request.path_params.get("path") or "index.html"
    user = current_user(request)
    if not user:
        here = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/signin?next={quote(safe_next(here), safe='')}", status_code=303)
    app = config.load_apps().get(name)
    if not app:
        return notice("App not found", [f"There is no app called {name}."], 404)
    if app["problems"]:
        return notice("This app is not published", app["problems"], 403)
    if user["role"] not in app["access"]:
        return notice("You don't have access to this app",
                      [f"Signed in as {user['name']} ({label(user['role'])})."], 403)
    if name in switches.off("app"):
        return notice("This app is turned off", [switches.why("app", name, app["title"])], 503)
    target = static_file(config.APPS_DIR / "apps" / name, rel)
    if not target:
        return notice("Not found", [rel], 404)
    return FileResponse(target, headers={"Content-Security-Policy": app_csp(), "Referrer-Policy": "same-origin",
                                         "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


async def serve_shared(request):
    target = static_file(config.APPS_DIR / "shared", request.path_params["path"])
    if not target or target.suffix.lower() == ".html":
        return JSONResponse({"error": "not found"}, status_code=404)
    # Shared files are only loaded by app pages. Opened directly, they may not run or load anything.
    return FileResponse(target, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                         "Content-Security-Policy": "default-src 'none'; sandbox"})


async def web_static(request):
    target = static_file(WEB, request.path_params["path"])
    if not target or target.suffix.lower() == ".html":
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target, headers={"Cache-Control": "no-store"})


# ---------- what an app can ask about the signed-in person ----------

def from_own_page(request, app_name):
    """A browser call to /api/<app>/ must come from that app's own pages, so one app's code can't use
    the signed-in person's grants in another app. Non-browser clients send no Sec-Fetch-Site; they
    can only do what the person could do anyway. On one shared origin this only guards against
    accidental cross-app calls (app code can forge the referrer or open another app's page); real
    isolation needs one subdomain per app plus the publish checks."""
    site = request.headers.get("sec-fetch-site")
    if site is None:
        return True
    referer = urlsplit(request.headers.get("referer", "")).path
    return site == "same-origin" and referer.startswith(f"/apps/{app_name}/")


async def me(request):
    user = current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Not signed in"}, status_code=401)
    if not from_own_page(request, request.path_params["app"]):
        return refuse(403, "Calls must come from this app's own pages")
    app = config.load_apps().get(request.path_params["app"])
    if not app or not can_open(user, app):
        return JSONResponse({"ok": False, "error": "You don't have access to this app"}, status_code=403)
    if app["name"] in switches.off("app"):
        return refuse(503, switches.why("app", app["name"], app["title"]))
    return JSONResponse({"ok": True, "data": {
        "user": {"name": user["name"], "role": user["role"], "title": label(user["role"]), "admin": is_admin(user)},
        "app": {"name": app["name"], "title": app["title"]},
        "tools": config.tools_for(app, user["role"]),
        "audit_trail": f"/audit/{app['name']}" if config.can_view_audit(user, app) else None,
    }})


def refuse(status, error):
    return JSONResponse({"ok": False, "error": error}, status_code=status)


async def call_tool(request):
    """POST /api/<app>/<connector>.<tool> with the inputs as a JSON object."""
    user = current_user(request)
    if not user:
        return refuse(401, "Not signed in")
    if not from_own_page(request, request.path_params["app"]):
        return refuse(403, "Calls must come from this app's own pages")
    app = config.load_apps().get(request.path_params["app"])
    if not app or not can_open(user, app):
        return refuse(403, "You don't have access to this app")
    name = request.path_params["tool"]
    tool = connectors.TOOLS.get(name)
    if not tool or tool.connector not in app["connectors"]:
        return refuse(404, f"This app has no tool called {name}")
    def log(outcome, detail="", inputs=None):
        if config.audited(app, tool):
            audit.record(app["name"], user, name, tool.kind, inputs or {}, outcome, detail,
                         retention_days=app["audit_retention_days"])

    if name not in config.tools_for(app, user["role"]):
        error = f"Your role ({label(user['role'])}) can't use {name} in this app"
        log("refused", error)
        return refuse(403, error)
    for kind, key, title in (("app", app["name"], app["title"]), ("connector", tool.connector, None), ("tool", name, None)):
        error = switches.why(kind, key, title)
        if error:
            log("refused", error)
            return refuse(503, error)
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return refuse(415, "Send inputs as JSON")
    try:
        body = await request.json()
    except ValueError:
        return refuse(400, "Inputs must be valid JSON")
    args, problem = connectors.check_inputs(tool.inputs, body)
    if problem:
        return refuse(400, problem)
    ctx = {"user": {"id": user["id"], "name": user["name"], "role": user["role"]}, "app": app["name"]}
    try:
        result = tool.handler(args, ctx)
    except connectors.ToolError as e:
        log("refused", str(e), args)
        return refuse(409, str(e))
    log("ok", inputs=args)
    return JSONResponse({"ok": True, "data": connectors.keep_declared(result, tool.returns)})


# ---------- each app's audit trail ----------

def audit_rows(rows, show_app=False):
    def cell(row):
        inputs = ", ".join(f"{k}: {v}" for k, v in row["inputs"].items())
        outcome = f'<span class="tag {"allowed" if row["outcome"] == "ok" else "refused"}">' \
                  f'{"OK" if row["outcome"] == "ok" else "Refused"}</span>'
        detail = f'<div class="note">{html.escape(row["detail"])}</div>' if row["detail"] else ""
        app_cell = ("" if not show_app else f'<td><a href="/audit/{html.escape(row["app"])}">{html.escape(row["app"])}</a></td>')
        return (f'<tr><td class="num">{html.escape(row["at"].replace("T", " ").rstrip("Z"))}</td>{app_cell}'
                f'<td>{html.escape(row["user_name"])}<div class="note">{html.escape(label(row["role"]))}</div></td>'
                f'<td><code>{html.escape(row["tool"])}</code> <span class="tag">{html.escape(row["kind"])}</span></td>'
                f'<td class="wrap-text">{html.escape(inputs) or "—"}</td><td>{outcome}{detail}</td></tr>')
    if not rows:
        return '<div class="empty"><strong>Nothing recorded yet</strong>Write calls and opted-in reads appear here.</div>'
    head = "<th>Time (UTC)</th>" + ("<th>App</th>" if show_app else "") + "<th>Who</th><th>Tool</th><th>Inputs</th><th>Result</th>"
    return f'<table class="log"><thead><tr>{head}</tr></thead><tbody>{"".join(cell(r) for r in rows)}</tbody></table>'


def topbar(user, crumbs):
    return page_fragment("topbar.html", crumbs=crumbs, tag=admin_tag(user), initials=html.escape(initials(user["name"])),
                         user=html.escape(user["name"]), role=html.escape(label(user["role"])))


def page_fragment(name, **values):
    text = (WEB / name).read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


async def audit_page(request):
    user = current_user(request)
    if not user:
        return RedirectResponse(f"/signin?next={quote(request.url.path, safe='')}", status_code=303)
    app = config.load_apps().get(request.path_params["app"])
    if not app:
        return notice("App not found", [f"There is no app called {request.path_params['app']}."], 404)
    if not config.can_view_audit(user, app):
        return notice("You can't view this audit trail",
                      [f"Signed in as {user['name']} ({label(user['role'])}).",
                       "Roles listed in the app's audit_viewers, and platform admins, can view it."], 403)
    if app["audit_retention_days"]:
        audit.prune(app["name"], app["audit_retention_days"])
    ok, broken = audit.verify(app["name"])
    chain = ('<span class="tag allowed">Chain intact</span>' if ok else
             f'<span class="tag refused">Chain broken at entry {broken}</span>')
    listed = ", ".join(app["audit"]) or "nothing"
    kept = (f'Kept for {app["audit_retention_days"]} days.' if app["audit_retention_days"]
            else "Kept until the app sets audit_retention_days.")
    crumbs = (f'<span class="crumb">/</span><span class="here">{html.escape(app["title"])}</span>'
              f'<span class="crumb">/</span><span class="here">Audit trail</span>')
    q = request.query_params
    chosen = {k: q.get(k, "").strip() for k in ("user", "tool", "kind", "outcome", "q")}
    people, tools = audit.facets(app["name"])
    rows = audit.entries(app["name"], limit=500, **{k: v or None for k, v in chosen.items()})

    def menu(name, blank, options):
        opts = "".join(f'<option value="{html.escape(v)}"{" selected" if chosen[name] == v else ""}>{html.escape(t)}</option>'
                       for v, t in [("", blank)] + list(options))
        return f'<select name="{name}" aria-label="{html.escape(blank)}">{opts}</select>'
    filters = (f'<form class="filters" method="get" action="/audit/{html.escape(app["name"])}">'
               f'<input type="search" name="q" value="{html.escape(chosen["q"])}" placeholder="Search people, tools, inputs, reasons">'
               + menu("user", "Anyone", people.items()) + menu("tool", "Any tool", [(t, t) for t in tools])
               + menu("kind", "Reads and writes", [("read", "Reads"), ("write", "Writes")])
               + menu("outcome", "Any result", [("ok", "OK"), ("refused", "Refused")])
               + '<button class="btn" type="submit">Filter</button>'
               + (f'<a class="btn ghost" href="/audit/{html.escape(app["name"])}">Clear</a>' if any(chosen.values()) else "")
               + '</form>')
    shown = f'{len(rows)} matching' if any(chosen.values()) else f'{len(rows)} entries'
    return page("audit.html", topbar=topbar(user, crumbs), title=html.escape(app["title"]), chain=chain,
                listed=html.escape(listed), kept=kept, filters=filters,
                shown=shown, rows=audit_rows(rows))


async def csp_report(request):
    """Browsers post here when the lockdown blocks something. Recorded once the audit log exists."""
    return Response(status_code=204)


# ---------- admin page (platform engineers) ----------

def tag(text, cls=""):
    return f'<span class="tag {cls}">{html.escape(text)}</span>'


async def admin_page(request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/signin?next=%2Fadmin", status_code=303)
    if user["role"] not in config.admin_roles():
        return notice("You can't open the admin page",
                      [f"Signed in as {user['name']} ({label(user['role'])}).", "Only platform admins can."], 403)
    apps, counts = config.load_apps(), audit.counts()
    off_apps, off_conns, off_tools = switches.off("app"), switches.off("connector"), switches.off("tool")

    def state(reason):
        return (f'{tag("Turned off", "refused")} <span class="note">{html.escape(reason)}</span>' if reason else
                tag("On", "published")) + '<div class="note">Change in switches.yaml</div>'

    people = "".join(f'<tr><td>{html.escape(u["name"])}</td><td>{html.escape(label(u["role"]))}</td>'
                     f'<td><code>{html.escape(u["role"])}</code></td>'
                     f'<td>{", ".join(html.escape(a["title"]) for a in apps.values() if can_open(u, a)) or "—"}</td></tr>'
                     for u in config.users().values())

    def connector_row(name):
        group = config.connector_group(name)
        tools = "".join(f'<div><code>{html.escape(t.name)}</code> {tag(t.kind)}'
                        f'{" " + tag("Turned off", "refused") if t.name in off_tools else ""} '
                        f'<span class="note">{html.escape(off_tools.get(t.name) or t.description)}</span></div>'
                        for t in connectors.TOOLS.values() if t.connector == name)
        used = ", ".join(html.escape(a["title"]) for a in apps.values() if name in a["connectors"]) or "—"
        control = state(off_conns.get(name)) if group != "blocked" else '<span class="note">Blocked by policy</span>'
        return (f'<tr><td><strong>{html.escape(name)}</strong></td><td>{tag(group.capitalize(), group)}</td><td>{tools}</td>'
                f'<td>{used}</td><td>{control}</td></tr>')
    conns = "".join(connector_row(c) for c in connectors.connectors())

    def app_parts(a):
        name = html.escape(a["name"])
        status = (tag("Not published", "refused") if a["problems"] else
                  tag("Turned off", "refused") if a["name"] in off_apps else tag("Published", "published"))
        problems = "".join(f'<div class="note">{html.escape(p)}</div>' for p in a["problems"])
        grants = "".join(
            f'<div><strong>{html.escape(label(r))}</strong>: '
            f'{", ".join(f"<code>{html.escape(t)}</code>" + (" (turned off)" if t in off_tools else "") for t in config.tools_for(a, r)) or "<span class=note>no tools</span>"}</div>'
            for r in a["access"] if r in config.ROLES) if not a["problems"] else '<span class="note">—</span>'
        granted = [] if a["problems"] else sorted({t for r in a["access"] for t in config.tools_for(a, r)})
        # Every tool on the app's connectors that the gateway would log, including refused attempts at ungranted ones.
        audited = [] if a["problems"] else [t for t in connectors.TOOLS.values()
                                            if t.connector in a["connectors"] and config.audited(a, t)]
        listed = "".join(f'<div><code>{html.escape(t.name)}</code> <span class="note">'
                         f'{"write, always" if t.kind == "write" else "read, listed in audit_reads"}'
                         f'{"" if t.name in granted else "; no role granted, refusals only"}</span></div>' for t in audited)
        conns = " ".join(tag(c, config.connector_group(c)) for c in a["connectors"]) or "—"
        viewers = ", ".join(html.escape(label(str(r))) for r in a["audit_viewers"]) or "none"
        n = counts.get(a["name"], 0)
        row = (f'<tr class="clickable" data-dialog="app-{name}" tabindex="0">'
               f'<td><strong>{html.escape(a["title"])}</strong><div class="note">{name}</div></td>'
               f'<td>{status}</td><td>{conns}</td>'
               f'<td>{len(audited)} tool{"s" if len(audited) != 1 else ""}</td><td class="num">{n}</td></tr>')

        def item(title, body):
            return f'<div class="item"><div class="item-label">{title}</div><div>{body}</div></div>'
        dialog = (f'<dialog id="app-{name}" class="modal"><div class="modal-head"><div><p class="eyebrow">{name}</p>'
                  f'<h2>{html.escape(a["title"])}</h2></div>{status}'
                  f'<button class="btn ghost" data-close aria-label="Close">Close</button></div>'
                  + (item("Why it isn't published", problems) if problems else
                     item("State", state(off_apps.get(a["name"]))))
                  + item("Description", html.escape(a.get("description") or "—"))
                  + item("Connectors", conns)
                  + item("Tools per role", grants)
                  + item("Audited tools", listed or '<span class="note">Nothing audited</span>')
                  + item("Audit retention", f'{a["audit_retention_days"]} days')
                  + item("Can view the trail", f'{viewers}, and platform admins')
                  + f'<div class="section-head gap"><span>Latest calls</span>'
                  f'<a href="/audit/{name}">Search all {n} entries →</a></div>'
                  + audit_rows(audit.entries(a["name"], limit=10)) + '</dialog>')
        return row, dialog
    parts = [app_parts(a) for a in apps.values()]
    app_rows, dialogs = "".join(r for r, _ in parts), "".join(d for _, d in parts)

    crumbs = '<span class="crumb">/</span><span class="here">Admin</span>'
    return page("admin.html", topbar=topbar(user, crumbs), people=people, connectors=conns, apps=app_rows, dialogs=dialogs,
                activity=audit_rows(audit.entries(limit=50), show_app=True))


def create_app():
    return Starlette(routes=[
        Route("/", portal),
        Route("/signin", signin, methods=["GET", "POST"]),
        Route("/signout", signout, methods=["GET", "POST"]),
        Route("/apps/{app}/", serve_app),
        Route("/apps/{app}/{path:path}", serve_app),
        Route("/shared/{path:path}", serve_shared),
        Route("/web/{path:path}", web_static),
        Route("/api/{app}/_me", me),
        Route("/api/{app}/{tool}", call_tool, methods=["POST"]),
        Route("/csp-report", csp_report, methods=["POST"]),
        Route("/audit/{app}", audit_page),
        Route("/admin", admin_page),
    ])


app = create_app()
