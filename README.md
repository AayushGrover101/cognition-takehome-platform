# cognition-takehome-platform

The engineer-owned half of an internal-tools platform. Apps live in
[cognition-takehome-apps](https://github.com/AayushGrover101/cognition-takehome-apps) and are built by
Devin. This repository is the gateway they all go through.

## What the gateway does

It is the only service that holds credentials or reaches data. Apps are static files that can only
ask it to run named operations. On every call it checks, in order:

1. Who is signed in.
2. That the operation is on the calling app's approved list (`app.yaml` in the apps repository).
3. Connector policy: the connector is not Blocked, the operation is not blocked, and the app does
   not combine Internal and External connectors.
4. That the person's role may open the app and run the operation.
5. That the inputs are the ones the operation accepts.
6. Business rules inside the operation, such as "refunds over 500 need a support lead".

It then hides fields the role may not see, and records the call in the audit log.

Apps are served with a browser rule (Content Security Policy) that only lets the page call its own
slice of the gateway. Anything the browser blocks is reported back and recorded.

## Layout

| Path | What it is |
| --- | --- |
| `connectors/*.yaml` | Operations per connector: roles, inputs, hidden fields, rules, audit limits |
| `policy.yaml` | Starting roles, people, connector groups and blocked operations |
| `gateway/main.py` | Sign-in, serving apps, the call path, admin API |
| `gateway/policy.py` | Whether an app's operation list is allowed |
| `gateway/audit.py` | Append-only audit log |
| `gateway/handlers.py` | What each operation does, on made-up data |
| `gateway/web/` | Sign-in, app list and admin pages |
| `scripts/export_catalog.py` | Writes the connector catalogue into the apps repository |

## Run it

```bash
pip install -r requirements.txt
APPS_DIR=../cognition-takehome-apps python3 -m uvicorn gateway.main:app --port 8090
python3 -m pytest tests
```

Open `http://localhost:8090`. Sign in as Sam Kim for the admin page at `/admin`.

## Audit log

- One row per call: who, role, app, operation, inputs, record, outcome and reason.
- On by default. An app may switch it off per operation, except for operations that change data or
  return hidden fields. Refused calls are always recorded.
- Retention and input masking are set per app, per operation. The connector sets the minimum and an
  app can only be stricter.
- Rows cannot be edited, and can only be deleted once their retention period has passed. The database
  enforces both. Each row carries a fingerprint of the previous row, so tampering is detectable.

## Prototype shortcuts

| Here | In production |
| --- | --- |
| Sign-in is a "pick who to be" page | Company single sign-on; roles from identity-provider groups |
| Operations return made-up data | Operations call real databases and APIs with credentials from a secrets store |
| Everything is served from one address, apps separated by path | One address per app, so the browser isolates apps from each other fully |
| SQLite file | Managed database, with the audit table writable only by the gateway |
| Admin page edits policy directly | Policy changes go through review in this repository |
| One gateway | A test gateway with made-up data for building, and a production gateway |
