"""The gateway: the only service that holds credentials or reaches data.

Every call from an app is checked here: who the user is, which app is calling, whether the operation is
on that app's approved list, whether connector policy allows it, and whether the user's role may run it.
"""
import html
import json
import os
import subprocess
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from . import audit, config, handlers, policy

WEB = Path(__file__).parent / "web"
STATIC_TYPES = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".ico", ".woff2"}
COOKIE = "gw_user"
REFUSED_DAYS = config.SEED.get("audit", {}).get("refused_retention_days", 2555)


# ---------- sign-in (stand-in for company single sign-on) ----------

def current_user(request):
    return config.users().get(request.cookies.get(COOKIE, ""))


def page(name, **values):
    text = (WEB / name).read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return HTMLResponse(text)


def safe_next(value):
    return value if value and value.startswith("/") and not value.startswith("//") else "/"


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
    rows = "".join(
        f'<button class="row" name="user" value="{html.escape(u["id"])}">'
        f'<span class="who">{html.escape(u["name"])}</span>'
        f'<span class="muted">{html.escape(u["role"].replace("_", " "))}</span>'
        f'{"<span class=tag>current</span>" if me and me["id"] == u["id"] else ""}</button>'
        for u in config.users().values()
    )
    return page("signin.html", rows=rows, next=html.escape(nxt, quote=True))


def app_status(app):
    problems = policy.evaluate_app(app)
    return ("blocked" if problems else "published"), problems


async def portal(request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/signin", status_code=303)
    cards = ""
    for app in config.load_apps().values():
        status, _ = app_status(app)
        if status != "published" or user["role"] not in app["access"]:
            continue
        cards += (
            f'<a class="card" href="/apps/{html.escape(app["name"])}/"><div class="title">{html.escape(app["title"])}</div>'
            f'<div class="muted">{html.escape(app.get("description", ""))}</div></a>'
        )
    if not cards:
        cards = '<p class="muted">No apps are available for your role yet.</p>'
    admin = '<a class="link" href="/admin">Admin</a>' if user["role"] == "admin" else ""
    return page("portal.html", cards=cards, admin=admin, user=html.escape(user["name"]),
                role=html.escape(user["role"].replace("_", " ")))


# ---------- serving apps (static files only) ----------

def public_origin(request):
    if os.environ.get("PUBLIC_ORIGIN"):
        return os.environ["PUBLIC_ORIGIN"].rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).split(",")[0].strip()
    return f"{proto}://{host}"


def app_csp(request, app_name):
    """The browser rule. The platform attaches it; app code cannot loosen it.

    The page may load files from this server and may only make calls to its own slice of the gateway.
    """
    return (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
        f"connect-src {public_origin(request)}/api/{app_name}/; "
        "form-action 'none'; base-uri 'none'; frame-src 'none'; object-src 'none'; "
        "sandbox allow-scripts allow-same-origin allow-downloads allow-modals; "
        "report-uri /csp-report"
    )


def static_file(root, rel):
    root = root.resolve()
    target = (root / rel).resolve()
    if root not in target.parents or not target.is_file() or target.suffix.lower() not in STATIC_TYPES:
        return None
    return target


def notice(title, lines, status):
    items = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    return HTMLResponse((WEB / "notice.html").read_text().replace("{{title}}", html.escape(title))
                        .replace("{{items}}", items), status_code=status)


async def serve_app(request):
    name, rel = request.path_params["app"], request.path_params.get("path") or "index.html"
    user = current_user(request)
    if not user:
        return RedirectResponse(f"/signin?next=/apps/{name}/", status_code=303)
    app = config.load_apps().get(name)
    if not app:
        return notice("App not found", [f"There is no app called {name}."], 404)
    status, problems = app_status(app)
    if status != "published":
        return notice("This app is not published", problems, 403)
    if user["role"] not in app["access"]:
        audit.record(user, name, "app.open", {}, "refused", f"Role {user['role']} may not open this app",
                     retention_days=REFUSED_DAYS)
        return notice("You don't have access to this app",
                      [f"Signed in as {user['name']} ({user['role'].replace('_', ' ')})."], 403)
    target = static_file(config.APPS_DIR / "apps" / name, rel)
    if not target:
        return notice("Not found", [rel], 404)
    return FileResponse(target, headers={"Content-Security-Policy": app_csp(request, name),
                                         "Cache-Control": "no-store"})


async def serve_shared(request):
    target = static_file(config.APPS_DIR / "shared", request.path_params["path"])
    if not target:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target, headers={"Cache-Control": "no-store"})


# ---------- the call path ----------

def validate(op, params):
    spec = op["params"]
    for key in params:
        if key not in spec:
            return f"Unknown input '{key}'"
    clean = {}
    for key, rule in spec.items():
        value = params.get(key)
        if value is None or value == "":
            if rule.get("required"):
                return f"Missing input '{key}'"
            continue
        kind = rule.get("type", "string")
        if kind == "enum" and value not in rule["values"]:
            return f"'{key}' must be one of {', '.join(rule['values'])}"
        if kind == "string" and not isinstance(value, str):
            return f"'{key}' must be text"
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return f"'{key}' must be a number"
        clean[key] = value
    return clean


def mask_value(style, value):
    text = str(value)
    if style == "last4":
        return "•••• " + text[-4:]
    if style == "year":
        return text[:4] + "-••-••"
    if style == "email" and "@" in text:
        return text[0] + "•••@" + text.split("@", 1)[1]
    return "••••"


def apply_masks(op, role, data):
    def one(row):
        if isinstance(row, dict):
            for field, rule in op["mask"].items():
                if field in row and row[field] is not None and role not in rule["show_full_to"]:
                    row[field] = mask_value(rule.get("style"), row[field])
        return row
    return [one(r) for r in data] if isinstance(data, list) else one(data)


async def call(request):
    app_name, operation = request.path_params["app"], request.path_params["operation"]
    user = current_user(request)
    try:
        params = json.loads(await request.body() or b"{}")
    except ValueError:
        params = None
    if not isinstance(params, dict):
        params = {}
    app = config.load_apps().get(app_name)
    op = config.OPERATIONS.get(operation)
    settings = {"enabled": True, "retention_days": 90, "mask_inputs": op["audit"]["mask_inputs"] if op else []}
    if app and op and operation in app["operations"]:
        settings = policy.audit_settings(app, operation)[0]
    record_id = params.get(op["record"]) if op and op.get("record") else None

    def refuse(status, reason):
        audit.record(user, app_name, operation, params, "refused", reason, record_id,
                     retention_days=REFUSED_DAYS, mask_inputs=settings["mask_inputs"])
        return JSONResponse({"ok": False, "error": reason}, status_code=status)

    if not user:
        return refuse(401, "Not signed in")
    if not app:
        return refuse(404, f"There is no app called {app_name}")
    if operation not in app["operations"]:
        return refuse(403, f"{operation} is not on this app's approved list")
    if not op:
        return refuse(403, f"{operation} is not in the connector catalogue")
    group = config.connector_groups()[op["connector"]]
    if group == "blocked":
        return refuse(403, f"The {op['connector']} connector is Blocked")
    if operation in config.blocked_operations():
        return refuse(403, f"{operation} has been blocked by an admin")
    problems = policy.evaluate_app(app)
    if problems:
        return refuse(403, "This app is not allowed under current policy: " + problems[0])
    if user["role"] not in app["access"]:
        return refuse(403, f"Role {user['role']} may not use this app")
    if user["role"] not in op["roles"]:
        return refuse(403, f"Role {user['role']} may not run {operation}")
    clean = validate(op, params)
    if isinstance(clean, str):
        return refuse(400, clean)
    try:
        data = handlers.handler_for(operation)(clean, user, app_name)
    except handlers.Refused as rule:
        return refuse(403, str(rule))
    data = apply_masks(op, user["role"], data)
    if settings["enabled"]:
        note = f"Returned {len(data)} records" if isinstance(data, list) else ""
        audit.record(user, app_name, operation, clean, "allowed", note, record_id,
                     retention_days=settings["retention_days"], mask_inputs=settings["mask_inputs"])
    return JSONResponse({"ok": True, "data": data})


async def me(request):
    user = current_user(request)
    app = config.load_apps().get(request.path_params["app"])
    if not user or not app:
        return JSONResponse({"ok": False, "error": "Not signed in"}, status_code=401)
    return JSONResponse({"ok": True, "data": {
        "user": {"name": user["name"], "role": user["role"]},
        "app": {"name": app["name"], "title": app["title"], "operations": app["operations"]},
    }})


async def csp_report(request):
    """Browsers post here when the browser rule blocks something an app tried to do."""
    try:
        report = json.loads(await request.body()).get("csp-report", {})
    except (ValueError, AttributeError):
        report = {}
    document = str(report.get("document-uri", ""))
    app_name = document.split("/apps/", 1)[1].split("/", 1)[0] if "/apps/" in document else ""
    blocked = str(report.get("blocked-uri", ""))[:300]
    audit.record(current_user(request), app_name, "browser.blocked",
                 {"address": blocked, "kind": str(report.get("effective-directive", ""))[:60]},
                 "refused", "Blocked by the browser rule: the app tried to reach an address it is not allowed to",
                 retention_days=REFUSED_DAYS)
    return JSONResponse({}, status_code=204)


# ---------- admin ----------

def require_admin(request):
    user = current_user(request)
    return user if user and user["role"] == "admin" else None


async def admin_page(request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/signin?next=/admin", status_code=303)
    if user["role"] != "admin":
        return notice("Admins only", [f"Signed in as {user['name']} ({user['role'].replace('_', ' ')})."], 403)
    return FileResponse(WEB / "admin.html", headers={"Cache-Control": "no-store"})


async def web_static(request):
    target = static_file(WEB, request.path_params["path"])
    if not target:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target, headers={"Cache-Control": "no-store"})


def admin_state(user):
    cat = config.catalog()
    connectors = []
    for name, meta in cat["connectors"].items():
        ops = [{"name": full, **op} for full, op in cat["operations"].items() if op["connector"] == name]
        connectors.append({"name": name, **meta, "operations": ops})
    apps = []
    for app in config.load_apps().values():
        status, problems = app_status(app)
        apps.append({
            "name": app["name"], "title": app["title"], "description": app.get("description", ""),
            "owner": app.get("owner", ""), "access": app["access"], "status": status, "problems": problems,
            "operations": [
                {"name": o, "group": cat["connectors"].get(o.split(".")[0], {}).get("group", "unknown"),
                 "audit": policy.audit_settings(app, o)[0] if o in config.OPERATIONS else None}
                for o in app["operations"]
            ],
        })
    return {"me": user, "roles": config.ROLES, "users": list(config.users().values()),
            "connectors": connectors, "apps": apps, "apps_dir": str(config.APPS_DIR)}


async def admin_api(request):
    user = require_admin(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Admins only"}, status_code=403)
    action = request.path_params["action"]
    if request.method == "GET":
        q = request.query_params
        if action == "state":
            return JSONResponse(admin_state(user))
        if action == "audit":
            rows = audit.search(q.get("user"), q.get("app"), q.get("operation"), q.get("record"), q.get("outcome"),
                                q.get("since"), q.get("until"))
            return JSONResponse({"rows": rows})
        if action == "audit-verify":
            return JSONResponse(audit.verify())
        if action == "outbox":
            rows = [dict(r) for r in config.db().execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 200")]
            return JSONResponse({"rows": rows})
        return JSONResponse({"ok": False, "error": "Unknown"}, status_code=404)

    body = json.loads(await request.body() or b"{}")

    def done(operation, inputs, **extra):
        audit.record(user, "admin", operation, inputs, "allowed", retention_days=REFUSED_DAYS)
        return JSONResponse({"ok": True, **extra})

    if action == "connector-group":
        name, group = body.get("connector"), body.get("group")
        if name not in config.CONNECTORS or group not in config.GROUPS:
            return JSONResponse({"ok": False, "error": "Unknown connector or group"}, status_code=400)
        groups = config.connector_groups()
        groups[name] = group
        config.set_setting("connector_groups", groups)
        return done("admin.set_connector_group", {"connector": name, "group": group})
    if action == "operation-block":
        operation, blocked = body.get("operation"), bool(body.get("blocked"))
        if operation not in config.OPERATIONS:
            return JSONResponse({"ok": False, "error": "Unknown operation"}, status_code=400)
        current = config.blocked_operations()
        (current.add if blocked else current.discard)(operation)
        config.set_setting("blocked_operations", sorted(current))
        return done("admin.set_operation_blocked", {"operation": operation, "blocked": blocked})
    if action == "user-role":
        target, role = body.get("user"), body.get("role")
        people = config.users()
        if target not in people or role not in config.ROLES:
            return JSONResponse({"ok": False, "error": "Unknown user or role"}, status_code=400)
        if target == user["id"]:
            return JSONResponse({"ok": False, "error": "You cannot change your own role"}, status_code=400)
        people[target]["role"] = role
        config.set_setting("users", list(people.values()))
        return done("admin.set_user_role", {"user": target, "role": role})
    if action == "sync-apps":
        try:
            out = subprocess.run(["git", "-C", str(config.APPS_DIR), "pull", "--ff-only"], capture_output=True,
                                 text=True, timeout=60)
            message = (out.stdout + out.stderr).strip()[-400:]
        except (OSError, subprocess.SubprocessError) as e:
            message = str(e)
        return done("admin.sync_apps", {}, message=message)
    if action == "reset-data":
        handlers.reset_data()
        return done("admin.reset_test_data", {})
    if action == "purge-expired":
        return done("admin.purge_expired_audit", {}, removed=audit.purge_expired())
    return JSONResponse({"ok": False, "error": "Unknown"}, status_code=404)


def create_app():
    audit.init()
    audit.purge_expired()
    return Starlette(routes=[
        Route("/", portal),
        Route("/signin", signin, methods=["GET", "POST"]),
        Route("/apps/{app}/", serve_app),
        Route("/apps/{app}/{path:path}", serve_app),
        Route("/shared/{path:path}", serve_shared),
        Route("/api/{app}/_me", me),
        Route("/api/{app}/{operation}", call, methods=["POST"]),
        Route("/csp-report", csp_report, methods=["POST"]),
        Route("/admin", admin_page),
        Route("/admin/api/{action}", admin_api, methods=["GET", "POST"]),
        Route("/web/{path:path}", web_static),
    ])


app = create_app()
