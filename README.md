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
| App top bar | `/web/topbar.js` | Apps include it to get the gateway's top bar: app name, who is signed in, and Sign out (back to sign-in, then to the same app). A signed-out link to an app goes through sign-in and lands on that app. |
| Portal | `/` | Lists only the apps whose `access` includes your role. |
| App hosting | `/apps/<app>/...` | Reads `APPS_DIR/apps/<app>/` on every request. Checks sign-in, a valid `app.yaml`, and that your role is in `access`, for every file. Serves static file types only, never outside the app folder. |
| Browser lockdown | `Content-Security-Policy` on app pages | The page loads files and sends requests only to the gateway. A browser call to `/api/<app>/` is refused unless it comes from that app's own pages, so one app can't use your grants in another. |
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
access: [kyc_analyst, compliance_officer]   # roles that can open the app
connectors: [kyc]                    # can't mix Internal and External; Blocked is refused
roles:                               # tools per role; anything not granted is denied
  kyc_analyst:
    tools: [kyc.list_cases, kyc.get_case, kyc.escalate_case]
  compliance_officer:
    tools: [kyc.*]                   # every kyc tool, including get_case_full and decide_case
```

Sensitive data is controlled by which tool a role gets: `kyc.get_case` returns the last four characters of the
tax ID, `kyc.get_case_full` returns all of it.

Responses are `{"ok": true, "data": ...}` or `{"ok": false, "error": "reason"}` with 400 (bad inputs), 401, 403
(no access or tool not granted), 404 (tool not available to this app), 409 (the system refused, e.g. already
decided) or 415 (not JSON).

## Section 3: audit

| Piece | Where | What it does |
| --- | --- | --- |
| What's recorded | `gateway/audit.py`, `config.audited` | Every **write** tool call, always. **Reads** only when the app lists them in `audit_reads`. Allowed calls and refusals (role not granted, or the system said no) are both recorded, with who, role, tool, inputs and result. The browser has no say. |
| One trail per app | SQLite `audit` table, keyed by app | Each app has its own sequence and SHA-256 hash chain (each entry includes the previous entry's hash), so each trail can be checked on its own. Editing or deleting an entry breaks the chain from that point. |
| Viewing | `/audit/<app>` | Roles in the app's `audit_viewers` and the platform's `admin_roles` (`policy.yaml`). Apps show an "Audit trail" link in the top bar for them. |

```yaml
audit_reads: [kyc.get_case_full]     # reads are off unless listed; writes are always audited
audit_viewers: [compliance_officer]  # who can see this app's trail
```

The database lives at `data/audit.db` (`AUDIT_DB` to change it). In production it would be an append-only store
that the gateway can insert into but not update.

## Section 4: admin page

`/admin`, for `admin_roles` (Sam Kim, Platform Engineer). Read-only; changes go through pull requests.

- **Apps:** published or not (with the reasons), connectors and their groups, the tools each role actually gets,
  how many write tools it can run, its opted-in reads, and a link to its audit trail.
- **Connectors:** group, every tool with read/write and description, which apps use it.
- **People and roles:** each person's role and the apps they can open.
- **Recent activity:** the latest 50 audit entries across apps.
