# cognition-takehome-platform

The gateway for the internal-tools app builder. **This is the repo you run.** It is owned by engineers.

Apps live in [cognition-takehome-apps](https://github.com/AayushGrover101/cognition-takehome-apps) as static files
(HTML/JS plus an `app.yaml`). The gateway reads them from that repo and serves them. It also:

- signs people in and shows a portal with the apps each person can open;
- runs every data request through **connectors**: named tools engineers write, such as `kyc.decide_case`;
- enforces each app's `app.yaml` on the server: which roles get which tools, and which fields are masked;
- writes each app's **audit trail**: nothing by default, only the tools the app opts in, hash-chained;
- locks the browser down so apps can only talk to the gateway;
- has an admin page (`/admin`) and kill switches (`switches.yaml`).

## Run it

Clone both repos next to each other, then:

```bash
cd cognition-takehome-platform
pip install -r requirements.txt
APPS_DIR=../cognition-takehome-apps python3 -m uvicorn gateway.main:app --port 8090
```

Open http://localhost:8090 and pick a person:

| Person | Role | Can |
| --- | --- | --- |
| Priya Shah | KYC Analyst | Use apps built for analysts. Sees masked fields only. |
| Dana Ortiz | Compliance Officer | Sees full KYC data and reads audit trails, where an app allows it. |
| Sam Kim | Platform Engineer | Admin: `/admin` and every audit trail. |

The portal is empty until an app exists in `cognition-takehome-apps/apps/`. The gateway re-reads that folder on every
request, so a new or changed app appears without a restart.

Tests: `python3 -m pytest tests`

## What's mocked

| Mocked | Here | In production |
| --- | --- | --- |
| SSO | Pick a person from a list. People and roles come from `policy.yaml`. | Your identity provider (Okta, Entra ID). Roles from groups. |
| Connectors | Made-up data in memory (`gateway/connectors/`). It resets when the gateway restarts. | The same tools, calling your real systems with credentials only the gateway holds. |
| Audit storage | SQLite at `data/audit.db` (change it with `AUDIT_DB`). | Append-only managed database, plus a copy of each trail's latest hash in write-once storage. |
| App hosting | Every app on one origin, at `/apps/<name>/`. | One subdomain per app, for stronger isolation between apps. |

## Where things are

| Path | What it is |
| --- | --- |
| `gateway/main.py` | Sign-in, portal, app hosting, tool calls, audit pages, admin page |
| `gateway/connectors/` | One file per system, with its tools (`kyc`, `refunds`, `flags`, `slack`, `gdrive`) |
| `gateway/audit.py` | Per-app audit trails |
| `policy.yaml` | Roles, people, admin roles, connector groups (Business / Non-business / Blocked) |
| `app_risk.yaml` | Apps whose code-only changes can publish without review. Every app not listed is high risk. |
| `switches.yaml` | Turn off an app, connector or single tool, with a reason |
| `.github/CODEOWNERS` | A platform engineer approves every change here |

After adding or changing a tool, refresh the catalogue the apps repo and Devin read:

```bash
python3 -m gateway.catalog > ../cognition-takehome-apps/platform/catalog.json
```
