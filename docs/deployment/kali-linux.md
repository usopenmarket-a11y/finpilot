# Deploy FinPilot on Kali Linux

Run the Next.js website and FastAPI backend in Docker. This setup uses your
**existing hosted Supabase project** for authentication and data; it does not
start a local database. The default stack also runs Caddy, which serves one
public URL, sends `/api/v1/*` to the API, and sends other requests to the
website. Caddy obtains and renews HTTPS certificates. To run everything on this
machine only, without a public domain, see [Local-only run](#local-only-run). See the
[architecture guide](../architecture.md) for the service boundaries.

## 1. Prepare the host and public name

- Use a domain or subdomain such as `finpilot.example.com`. Point its DNS `A`
  record to the host's public IPv4 address. Add an `AAAA` record only if IPv6
  reaches this host. If the host is behind a router, forward TCP ports **80 and
  443** to it. Forward UDP 443 if you want HTTP/3. Allow those ports through
  the host/network firewall. If the connection uses CGNAT and has no public
  inbound address, use a tunnel or another public ingress instead.
- The bundled Caddy setup needs ports 80 and 443 free. If another reverse
  proxy already owns them, use the [existing proxy option](#existing-reverse-proxy)
  below.
- Install Git, Docker Engine, and the Docker Compose plugin if needed. Kali's
  [Docker installation guide](https://www.kali.org/docs/containers/installing-docker-on-kali/)
  covers the engine; [Docker's Debian guide](https://docs.docker.com/engine/install/debian/)
  describes the official repository and the Compose plugin. On Kali, use the
  corresponding Debian release codename when following Docker's repository
  instructions. Verify the installation:

  ```sh
  docker --version
  docker compose version
  sudo systemctl enable --now docker
  ```

Use `sudo docker compose` in the commands below if your account cannot access
the Docker daemon. Do not install the unrelated Kali package named `docker`.

## 2. Clone and configure

```sh
git clone https://github.com/usopenmarket-a11y/finpilot.git finpilot
cd finpilot
cp .env.example .env
cp apps/api/.env.production.example apps/api/.env
chmod 600 .env apps/api/.env
```

Edit `.env`:

| Variable | Value |
| --- | --- |
| `SITE_DOMAIN` | Your public hostname, without `https://` or a trailing slash. |
| `NEXT_PUBLIC_SUPABASE_URL` | The URL of your existing Supabase project. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | That project's public anon key. |

Edit `apps/api/.env`:

| Variable | Value |
| --- | --- |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key from the same Supabase project; server only. |
| `SUPABASE_JWT_SECRET` | The legacy HS256 JWT secret if this Supabase project uses it. JWKS-signed access tokens are verified through the project's JWKS endpoint. |
| `ENCRYPTION_KEY` | Existing key if migrating an active installation; otherwise generate with `openssl rand -hex 32`. It must be 64 hex characters. |
| `CLAUDE_API_KEY` | Anthropic API key for AI categorization, if used. |
| `BDC_PROXY_*` | Egyptian sticky HTTP(S) proxy settings if BDC sync is used. The current production BDC scraper requires these. See [bank-sync.md](../bank-sync.md). |

Keep the **same** `ENCRYPTION_KEY` when moving an existing installation, or
stored bank credentials cannot be decrypted. Never put the service role key,
JWT secret, encryption key, or proxy password in `NEXT_PUBLIC_*` variables.
Both `.env` files are ignored by Git and excluded from Docker build contexts.

In the Supabase dashboard, set the Auth site URL to
`https://<SITE_DOMAIN>` and allow these redirect URLs:

```text
https://<SITE_DOMAIN>/auth/callback
https://<SITE_DOMAIN>/auth/callback?next=/auth/update-password
```

If this is a personal-only installation, create your account and then disable
"Allow new users to sign up" in Supabase Auth's
[general configuration](https://supabase.com/docs/guides/auth/general-configuration).

This repo contains incremental SQL migrations, not a complete initial schema.
Use the existing Supabase project that already runs FinPilot. A new Supabase
project needs its base schema and policies before this deployment will work.
Check [the database guide](../database.md) for migration order and the
September 2026 change that must precede matching application code.

## 3. Start the containers

```sh
docker compose -f compose.prod.yml config --quiet
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml ps
```

The first build downloads Python and Node dependencies plus Playwright and
Patchright Chromium, so it may take several minutes and several GB of disk.
Caddy's `caddy_data` volume stores TLS certificates; leave that volume in
place during upgrades. Once DNS and inbound ports are working, open
`https://<SITE_DOMAIN>` and check the API:

```sh
curl -fsS https://<SITE_DOMAIN>/api/v1/health
```

The expected response includes `"status":"ok"`. The website and API are
available through the same HTTPS origin. Ports 3000 and 8000 are internal to
Docker in this setup. To see startup errors:

```sh
docker compose -f compose.prod.yml logs --tail=100 caddy web api
```

If Caddy cannot get a certificate, verify DNS, external port forwarding, and
that nothing else owns host ports 80/443. [Caddy's HTTPS requirements](https://caddyserver.com/docs/automatic-https)
describe the public DNS and port checks.

## Local-only run

To use FinPilot only on this machine, without a domain, DNS, port forwarding,
or TLS, add `compose.local.yml`. It disables Caddy and publishes the website
and API on loopback over plain HTTP. Configure the two `.env` files as in
[step 2](#2-clone-and-configure), with these differences:

- Set `SITE_DOMAIN=localhost` in `.env`. Compose requires the variable; the
  local override replaces every URL derived from it.
- In Supabase Auth, add `http://localhost:3000/auth/callback` and
  `http://localhost:3000/auth/callback?next=/auth/update-password` to the
  allowed redirect URLs. Keep the public site URL if one is configured.
- The override sets `APP_ENV=development`, so BDC sync connects directly
  instead of requiring the Egyptian proxy. A direct connection works only from
  an Egyptian network; otherwise set the `BDC_PROXY_*` values.

```sh
docker compose -f compose.prod.yml -f compose.local.yml config --quiet
docker compose -f compose.prod.yml -f compose.local.yml up -d --build
docker compose -f compose.prod.yml -f compose.local.yml ps
curl -fsS http://localhost:8000/api/v1/health
curl -fsS http://localhost:3000/api/v1/health
```

Open `http://localhost:3000`. The browser calls `/api/v1/*` on that origin and
the web server forwards those requests to the API container. The second
`curl` checks that forwarding. The API is also published at
`http://127.0.0.1:8000`, where development mode serves its `/docs` page. Set
`LOCAL_WEB_PORT` or `LOCAL_API_PORT` in `.env` if those ports are taken; the
Supabase redirect URLs must then use the new web port. Both ports bind to
127.0.0.1 only, so other devices on the network cannot reach them.

The web image embeds its URLs at build time. Use `--build` whenever you switch
between the local and public setups, and use the same `-f` files for `ps`,
`logs`, `down`, and updates.

## Existing reverse proxy

If this Kali machine already runs an HTTPS reverse proxy, use the included
override instead of the bundled Caddy service:

```sh
docker compose -f compose.prod.yml -f compose.prod.existing-proxy.yml up -d --build
```

The override binds the web app to `127.0.0.1:13000` and the API to
`127.0.0.1:18000`. Configure your existing proxy to send
`https://<SITE_DOMAIN>/api/v1/*` to `http://127.0.0.1:18000` and all other
paths to `http://127.0.0.1:13000`, preserving the request path and forwarding
the original host and HTTPS scheme. It must provide a valid TLS certificate.
You can change the loopback ports by setting `WEB_BIND_PORT` and
`API_BIND_PORT` in `.env`. Re-run the same Compose command for updates. If
switching from the bundled Caddy setup, run the first update with
`--remove-orphans` to remove its old container.

## Updating and operations

```sh
git pull --ff-only
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml ps
```

Use the matching two-file Compose command for updates if using the local
override or an existing proxy.
To stop the application without deleting TLS data, run
`docker compose -f compose.prod.yml down`. Back up your Supabase project and
the two private `.env` files separately. Do not use `down -v` during routine
updates because it removes the Caddy certificate volumes.

The API runs one container because sync job state is held in memory while a
job is active. Restarting it during a sync can interrupt that job. A Kali host
outside Egypt may also need the Egyptian proxy for BDC connectivity. Browser
scraping needs enough memory; the API container allows up to 1 GB of shared
memory for Chromium, so plan sufficient host RAM.
