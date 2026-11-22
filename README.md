# cognition-takehome-platform

Gateway for the internal-tools app builder (engineer-owned). Apps are static files in
[cognition-takehome-apps](https://github.com/AayushGrover101/cognition-takehome-apps); the gateway signs people in,
decides who can open each app, and serves the app's files with a browser lockdown.

## Run

```bash
pip install -r requirements.txt
APPS_DIR=../cognition-takehome-apps python3 -m uvicorn gateway.main:app --port 8090
python3 -m pytest tests
```

## What's here (section 1: gateway core)

| Piece | Where | What it does |
| --- | --- | --- |
| Sign-in | `/signin`, `/signout`, `policy.yaml` | Mocked single sign-on: choose an account from a dropdown; the role comes from `policy.yaml`. Sets an HTTP-only cookie. |
| Portal | `/` | Lists only the apps whose `access` includes your role. |
| App hosting | `/apps/<app>/...` | Reads `APPS_DIR/apps/<app>/` on every request. Checks sign-in, a valid `app.yaml`, and that your role is in `access`, for every file. Serves static file types only, never outside the app folder. |
| Browser lockdown | `Content-Security-Policy` on app pages | The page loads files only from the gateway and may send requests only to `/api/<app>/`. |
| Shared files | `/shared/...` | Common JS/CSS from `APPS_DIR/shared/`, locked down if opened directly. |
| `_me` | `/api/<app>/_me` | The signed-in person's name and role, for apps that can open this app. |

## Section 2: connectors and tool calls

| Piece | Where | What it does |
| --- | --- | --- |
| Connectors | `gateway/connectors/<name>.py` | One per system. Each tool has a name, inputs, the fields it returns and whether it reads or writes. Engineers write them; they hold the credentials (made-up data here). |
| Connector groups | `policy.yaml` → `connectors` | Internal, External or Blocked. A connector not listed counts as Blocked. |
| Tool calls | `POST /api/<app>/<connector>.<tool>` | Checks sign-in, app access, that the tool's connector is declared by the app, that the role is granted the tool, and the inputs. Returns only the declared fields. |
| Client | `/web/gateway.js` | `gateway.call('kyc.get_case', {case_id})` and `gateway.me()`. Refusals throw an `Error` with the reason. |

`app.yaml`:

```yaml
title: KYC review queue
description: Review and decide pending KYC cases.
access: [analyst, senior_reviewer]   # roles that can open the app
connectors: [kyc]                    # can't mix Internal and External; Blocked is refused
roles:                               # tools per role; anything not granted is denied
  analyst:
    tools: [kyc.list_cases, kyc.get_case, kyc.escalate_case]
  senior_reviewer:
    tools: [kyc.*]                   # every kyc tool, including get_case_full and decide_case
```

Sensitive data is controlled by which tool a role gets: `kyc.get_case` returns the last four characters of the
tax ID, `kyc.get_case_full` returns all of it.

Responses are `{"ok": true, "data": ...}` or `{"ok": false, "error": "reason"}` with 400 (bad inputs), 401, 403
(no access or tool not granted), 404 (tool not available to this app), 409 (the system refused, e.g. already
decided) or 415 (not JSON).
