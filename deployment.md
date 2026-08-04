# FastAPI Project - Deployment

The production entry point is the frontend Nginx container. Browsers use the
public frontend origin for pages, `/api/v1/...`, `/docs`, and `/redoc`. Nginx
proxies those backend paths, so normal UI traffic stays same-origin.

TLS certificates and HTTP-to-HTTPS redirects are handled by an external load
balancer or reverse proxy. Traffic between that component and the containers,
and between application VMs, uses private HTTP.

For full topology examples and operational commands, see the Korean
[multi-VM deployment guide](deploy_guide.md).

## Production profiles

Set `COMPOSE_PROFILES` independently on every VM:

- `db,backend,frontend`: all services on one VM
- `db`: database VM
- `backend`: migration job and API VM
- `frontend`: Nginx and static frontend VM
- Any two profiles: a two-component VM in a split deployment

Deploy without the local override:

```bash
docker compose -f compose.yml config --quiet
docker compose -f compose.yml build
docker compose -f compose.yml up -d
```

## Required deployment interface

- `COMPOSE_PROFILES`: components started on this VM
- `FRONTEND_HOST`: public HTTPS origin, such as `https://admin.example.com`
- `BACKEND_UPSTREAM`: backend URL reachable from the frontend container, with
  no trailing slash
- `POSTGRES_SERVER`: database service name or private address reachable from
  backend containers
- `DB_BIND_ADDRESS`, `BACKEND_BIND_ADDRESS`, `FRONTEND_BIND_ADDRESS`: host
  addresses for published ports
- `VITE_API_URL`: empty for same-origin production traffic; a non-empty value
  requires rebuilding the frontend image
- `BACKEND_CORS_ORIGINS`: additional frontend origins that directly call the
  backend

Keep `VITE_API_URL` and `BACKEND_CORS_ORIGINS` empty for the normal production
setup. `FRONTEND_HOST` is always included in the backend allowlist because it is
also used to generate password-reset links.

## Network policy

Allow only these directional paths:

- External load balancer to frontend VM TCP 80
- Frontend VM to backend VM TCP 8000 when split
- Backend VM to database VM TCP 5432 when split

Do not expose backend or database ports to the public internet. Bind them to a
specific private interface and enforce the source restriction in the VM or
cloud firewall.

## GitHub Actions deployments

The staging and production workflows use environment-scoped configuration.
Configure these GitHub Environment variables for each deployment target:

- `COMPOSE_PROFILES`
- `FRONTEND_HOST`
- `BACKEND_UPSTREAM`
- `POSTGRES_SERVER`
- `DB_BIND_ADDRESS`
- `BACKEND_BIND_ADDRESS`
- `FRONTEND_BIND_ADDRESS`
- `VITE_API_URL` (normally empty)
- `BACKEND_CORS_ORIGINS` (normally empty)

Continue to store passwords and token keys as environment secrets, including
`SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, and `POSTGRES_PASSWORD`. A runner only
deploys the profiles assigned to its VM; split deployments therefore need a
runner or equivalent deployment step on each participating VM.
