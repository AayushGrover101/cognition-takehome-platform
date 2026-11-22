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
| Sign-in | `/signin`, `policy.yaml` | Mocked single sign-on: pick a person; their role comes from `policy.yaml`. Sets an HTTP-only cookie. |
| Portal | `/` | Lists only the apps whose `access` includes your role. |
| App hosting | `/apps/<app>/...` | Reads `APPS_DIR/apps/<app>/` on every request. Checks sign-in, a valid `app.yaml`, and that your role is in `access`, for every file. Serves static file types only, never outside the app folder. |
| Browser lockdown | `Content-Security-Policy` on app pages | The page loads files only from the gateway and may send requests only to `/api/<app>/`. |
| Shared files | `/shared/...` | Common JS/CSS from `APPS_DIR/shared/`, locked down if opened directly. |
| `_me` | `/api/<app>/_me` | The signed-in person's name and role, for apps that can open this app. |

Minimal `app.yaml` at this stage:

```yaml
title: KYC review queue
description: Review and decide pending KYC cases.
access: [analyst, senior_reviewer]   # roles that can open the app
```
