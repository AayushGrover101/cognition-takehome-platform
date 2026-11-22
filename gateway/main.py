"""The gateway: sign-in, the portal, and serving app files to people allowed to open them."""
import html
from pathlib import Path
from urllib.parse import quote, urlsplit

from starlette.applications import Starlette
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import config, connectors

WEB = Path(__file__).parent / "web"
STATIC_TYPES = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".ico", ".woff2"}
COOKIE = "gw_user"


# ---------- sign-in (stand-in for company single sign-on) ----------

def current_user(request):
    return config.users().get(request.cookies.get(COOKIE, ""))


def label(role):
    return config.ROLES.get(role, role)


def page(name, status=200, **values):
    text = (WEB / name).read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return HTMLResponse(text, status_code=status)


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
        f'{html.escape(u["name"])} — {html.escape(label(u["role"]))}</option>'
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
    arrow = ('<svg class="go" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5" '
             'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    cards = "".join(
        f'<a class="app" href="/apps/{html.escape(app["name"])}/"><span class="icon">{html.escape(initials(app["title"]))}</span>'
        f'<span class="text"><div class="title">{html.escape(app["title"])}</div>'
        f'<div class="desc">{html.escape(str(app.get("description", "")))}</div></span>{arrow}</a>'
        for app in apps
    )
    cards = f'<div class="apps">{cards}</div>' if apps else (
        '<div class="empty"><strong>No apps yet</strong>Nothing is available for your role. '
        'Ask your team lead if you expected to see an app here.</div>')
    count = f'{len(apps)} app{"" if len(apps) == 1 else "s"}'
    return page("portal.html", cards=cards, count=count, first=html.escape(user["name"].split()[0]), initials=html.escape(initials(user["name"])),
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
    return JSONResponse({"ok": True, "data": {
        "user": {"name": user["name"], "role": user["role"], "title": label(user["role"])},
        "app": {"name": app["name"], "title": app["title"]},
        "tools": config.tools_for(app, user["role"]),
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
    if name not in config.tools_for(app, user["role"]):
        return refuse(403, f"Your role ({label(user['role'])}) can't use {name} in this app")
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
        return refuse(409, str(e))
    return JSONResponse({"ok": True, "data": connectors.keep_declared(result, tool.returns)})


async def csp_report(request):
    """Browsers post here when the lockdown blocks something. Recorded once the audit log exists."""
    return Response(status_code=204)


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
    ])


app = create_app()
