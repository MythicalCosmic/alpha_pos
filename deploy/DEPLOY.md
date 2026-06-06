# Server deploy — Alpha POS cloud + Control Center (IP-only, auto-HTTPS)

Two Docker Compose stacks on one Linux server, behind a Caddy reverse proxy that
gets **real Let's Encrypt HTTPS** with no domain via **nip.io**:

| Service | URL |
|---|---|
| Alpha POS cloud backend | `https://pos.<IP>.nip.io` |
| POS Control Center | `https://control.<IP>.nip.io` |

`<IP>` = your server's public IP, e.g. `203.0.113.10` → `pos.203.0.113.10.nip.io`.
nip.io resolves that name to the IP automatically — nothing to register.

## Prerequisites
- Linux server with Docker + Docker Compose v2.
- Ports **80 and 443 open** to the internet (Caddy needs 80/443 for the cert
  challenge + serving). The app ports (8000) are **not** exposed publicly.
- A GitHub login that can read both repos.

## Steps (run on the SERVER)

```bash
# 1. Get both repos side by side
#    (alpha_pos deploy bundle + prelaunch fixes live on the prelaunch-fixes branch)
cd ~
git clone -b prelaunch-fixes https://github.com/MythicalCosmic/alpha_pos.git
git clone https://github.com/MythicalCosmic/pos_control.git

# 2. Deploy (replace with your real public IP)
cd ~/alpha_pos/deploy
chmod +x deploy.sh
./deploy.sh 203.0.113.10
```

`deploy.sh` generates `.env` files (with fresh secrets), the Caddyfile, and the
compose overrides, then builds and starts **alpha_pos**, **pos_control**, and
**caddy**. It prints the one-time finishing commands (license the cloud, create
admins) — run those, then verify:

```bash
curl -fsS https://pos.<IP>.nip.io/healthz      # -> ok
curl -fsSI https://control.<IP>.nip.io/ | head -1
```

> First HTTPS hit can take ~30s while Caddy obtains certificates. If it fails,
> check `docker compose logs caddy` in `~/alpha_pos/deploy/caddy` — the usual
> cause is port 80/443 not reachable from the internet.

## Point a desktop POS at these servers

In the desktop control panel → **Configuration**:
- `LICENSE_CONTROL_CENTER_URL = https://control.<IP>.nip.io`
- `CLOUD_SYNC_URL = https://pos.<IP>.nip.io`
- `CLOUD_SYNC_TOKEN = ` (the token deploy.sh printed)
- `SYNC_ENABLED = True`

Then **License & Subscription → Register** (after you create a tenant in the
control center), and run a sale to test sync.

## Updating after a code change
```bash
cd ~/alpha_pos   && git pull && docker compose -f docker-compose.yaml -f docker-compose.edge.yml up -d --build
cd ~/pos_control && git pull && docker compose -f docker-compose.yaml -f docker-compose.edge.yml up -d --build
```

## Useful
```bash
# logs
cd ~/alpha_pos && docker compose -f docker-compose.yaml -f docker-compose.edge.yml logs -f web
# restart everything
cd ~/alpha_pos/deploy && ./deploy.sh <IP>
```

Secrets live only in the generated `.env` files (gitignored). Re-running
`deploy.sh` preserves existing secrets so the database keeps working.
