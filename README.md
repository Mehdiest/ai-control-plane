# AI Control Plane

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-336791?style=flat&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat&logo=redis&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat&logo=sqlalchemy&logoColor=white)
![Alembic](https://img.shields.io/badge/Alembic-1.18-6BA81E?style=flat)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat&logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-43%20passed-brightgreen?style=flat&logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)
![Status](https://img.shields.io/badge/Status-Phase%204%20Complete-blue?style=flat)

A lightweight control plane for AI services — service registration, background health checking, network-aware policy-based routing, per-tenant rate limiting, and observability. Applies control-plane / data-plane separation, topology-aware routing, and quota enforcement from traditional networking to AI infrastructure.

## Origin

This project grew out of a real need inside the
[Enterprise AI Business Intelligence Platform](https://github.com/Mehdiest/Enterprise-AI-Business-Intelligence-Platform):
reliably knowing whether an LLM provider or downstream service was actually
reachable before routing a request to it. The BI Platform is the first
service registered with this control plane, but the control plane itself is
generic — it can register and govern any HTTP-based AI service.

## Phase 1 — Service Registry & Health Checking ✅

- **Service Registry**: register, list, fetch, and deregister downstream services via REST API.
- **Background Health Checking**: APScheduler polls every registered service on a configurable interval — the same way a router marks a BGP neighbor up or down based on consecutive missed keepalives.
- **Status Model**: `UNKNOWN → HEALTHY / DEGRADED → UNHEALTHY` based on a configurable consecutive-failure threshold.
- **Admin Status Override**: manually force a service into any health state — equivalent of `shutdown` / `no shutdown` on a network interface.

## Phase 2 — Policy-Based Routing ✅

- **Policy Engine**: evaluates active routing policies in priority order — mirroring route-map clause evaluation in traditional network policy-based routing.
- **Network-Aware Routing**: services carry topology metadata (region, latency zone, network tags); policies can constrain routing to specific regions or latency classes — analogous to BGP community filtering and OSPF link-cost preference.
- **Automatic Failover**: if the primary target fails health or topology checks, the engine transparently falls back to the configured secondary.
- **Policy Fallthrough**: when a constrained policy finds no eligible service, evaluation continues to the next policy in priority order — mirroring route-map clause fallthrough.
- **Conflict Validation**: no two active policies for the same request type may share the same priority — enforced on both create and update.
- **Resolution Codes**: every routing decision returns a typed outcome (`primary`, `fallback`, `no_policy`, `no_healthy_service`).

## Phase 3 — Rate Limiting & Quota per Tenant ✅

- **Per-Tenant Quota**: each tenant gets a configurable request ceiling within a time window (`max_requests / window_seconds`).
- **Redis-Backed Counting**: fixed-window counter using `INCR` + `EXPIRE` — lightweight and sub-millisecond.
- **JWT Tenant Extraction**: `tenant_id` is read from the Bearer token before each route resolution; unauthenticated requests fall under a shared `anonymous` bucket.
- **Graceful Defaults**: tenants without a quota record, or with `is_active=False`, pass through without counting.
- **429 with Headers**: quota-exceeded responses include `Retry-After`, `X-RateLimit-Limit`, and `X-RateLimit-Remaining`.
- **Quota Management API**: create, inspect (with live Redis counter), update, and reset quotas via REST.

## Phase 4 — Observability Dashboard ✅

- **Request Logging**: every call to `/route` is logged asynchronously (via `BackgroundTasks`) with tenant, request type, resolved service, resolution code, and latency — without adding to the critical path.
- **Summary Endpoint**: snapshot of service health counts, active policy count, and request volume in the last hour.
- **Traffic Metrics**: distribution of resolved services and resolution codes over a configurable time window.
- **Error Metrics**: breakdown of error-class resolutions (`no_policy`, `no_healthy_service`) per service.
- **Latency Metrics**: average routing latency per resolved service, ordered fastest first.

## Architecture

```
Request → JWT decode → tenant_id
                           │
                     Redis counter
                     INCR + EXPIRE
                           │
                    quota check (DB)
                    ┌──────┴──────┐
                  pass           429
                    │
             Policy Engine
             priority sort
             → region / latency filter
             → health check
             → primary / fallback / fallthrough
                    │
           Downstream AI Service
                    │
             BackgroundTask
             → RequestLog (DB)
```

```
┌──────────────────────────────────────────────────────┐
│                  FastAPI Application                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │ Registry │ │ Policies │ │  Quotas  │ │ Observe │ │
│  │   API    │ │ + /route │ │   API    │ │   API   │ │
│  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
│  ┌────────────────────────────────────────────────┐   │
│  │       APScheduler — Health Check Cycle          │   │
│  └────────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────┐   │
│  │   Policy Engine + Rate Limiter + Observer       │   │
│  └────────────────────────────────────────────────┘   │
└───────────────────┬────────────────────────────────---┘
                    │
       ┌────────────┴────────────┐
       ▼                         ▼
  PostgreSQL + Alembic         Redis 7
  (services, policies,         (rate limit counters)
   quotas, request_logs)
```

## Network Topology Model

| Attribute | Type | Analogy |
|---|---|---|
| `region` | string (`eu-west`, `on-premise`) | BGP community — restricts routing to certain zones |
| `latency_zone` | enum `low / medium / high` | OSPF link cost — lower cost paths preferred |
| `network_tags` | list of strings (`gpu`, `air-gapped`) | BGP extended communities — free-form route filtering |

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 18 |
| Migrations | Alembic 1.18 |
| Cache / Rate Limiting | Redis 7 (async via redis-py) |
| Auth | python-jose (JWT) |
| Scheduling | APScheduler 3.x |
| HTTP Client | httpx (async) |
| Validation | Pydantic v2 |
| Testing | pytest + pytest-asyncio + fakeredis |
| Containerization | Docker / docker-compose |

## Project Structure

```
ai-control-plane/
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── api/v1/
│   │   ├── __init__.py
│   │   ├── registry.py         # service CRUD + status override
│   │   ├── policies.py         # policy CRUD + /route (rate limit + logging)
│   │   ├── quotas.py           # quota CRUD + live counter + reset
│   │   └── observe.py          # summary, traffic, errors, latency endpoints
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── redis.py
│   │   └── security.py         # JWT → tenant_id
│   ├── models/
│   │   ├── service.py          # Service + ServiceStatus + LatencyZone
│   │   ├── policy.py           # Policy with network match conditions
│   │   ├── quota.py            # Quota per tenant
│   │   └── request_log.py      # RequestLog for observability
│   ├── schemas/
│   │   ├── service.py
│   │   ├── policy.py
│   │   ├── quota.py
│   │   └── observe.py          # ObserveSummary, TrafficEntry, ErrorStats, LatencyStats
│   ├── services/
│   │   ├── health_checker.py
│   │   ├── policy_engine.py
│   │   ├── rate_limiter.py
│   │   └── observer.py         # read-only query aggregations
│   └── main.py
├── tests/
│   ├── conftest.py
│   ├── test_health_checker.py  # 7 tests
│   ├── test_policy_conflicts.py # 4 tests
│   ├── test_policy_engine.py   # 13 tests
│   ├── test_rate_limiter.py    # 13 tests
│   └── test_observe.py         # 6 tests
├── pytest.ini
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Getting Started

### Prerequisites
- Python 3.12+
- PostgreSQL 18+
- Redis 7+ (or `docker run -d --name redis -p 6379:6379 redis:7-alpine`)

### Local setup
```bash
cp .env.example .env
# edit DATABASE_URL, REDIS_URL, JWT_SECRET_KEY in .env
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### Full Docker
```bash
docker-compose up --build
```

API docs: `http://localhost:8000/docs`

### Run tests
```bash
python -m pytest tests/ -v --timeout=15
```

> ⚠️ **Production note**: never deploy with default credentials from `.env.example`.
> Always set strong values for `DATABASE_URL`, `REDIS_URL`, and `JWT_SECRET_KEY`.

## API Endpoints

### Registry

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/registry` | Register a service (with region, latency_zone, network_tags) |
| `GET` | `/api/v1/registry` | List all services + aggregate health summary |
| `GET` | `/api/v1/registry/{id}` | Fetch a single service |
| `PATCH` | `/api/v1/registry/{id}/status` | Override a service's health status |
| `DELETE` | `/api/v1/registry/{id}` | Deregister a service |

### Policies & Routing

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/policies` | Create a routing policy |
| `GET` | `/api/v1/policies` | List all policies ordered by priority |
| `GET` | `/api/v1/policies/{id}` | Fetch a single policy |
| `PATCH` | `/api/v1/policies/{id}` | Update a policy (conflict-checked) |
| `DELETE` | `/api/v1/policies/{id}` | Delete a policy |
| `POST` | `/api/v1/route` | Resolve which service handles a request (rate-limited + logged) |

### Quotas

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/quotas` | Create a quota for a tenant |
| `GET` | `/api/v1/quotas/{tenant_id}` | Fetch quota + live Redis counter |
| `PATCH` | `/api/v1/quotas/{tenant_id}` | Update quota limits or active flag |
| `DELETE` | `/api/v1/quotas/{tenant_id}/counter` | Reset the Redis counter for a tenant |

### Observability

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/observe/summary` | Snapshot: service health, active policies, request volume |
| `GET` | `/api/v1/observe/traffic?hours=1` | Traffic distribution by service and resolution |
| `GET` | `/api/v1/observe/errors?hours=1` | Error breakdown by service |
| `GET` | `/api/v1/observe/latency?hours=1` | Average latency per service |

### Meta

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check for the control plane itself |

## Roadmap

- ✅ **Phase 1** — Service Registry & Health Checking
- ✅ **Phase 2** — Policy-Based Routing with Network-Aware Constraints
- ✅ **Phase 3** — Rate Limiting & Quota per Tenant
- ✅ **Phase 4** — Observability Dashboard
- 🔲 **Phase 5** — Canary Rollout support

## License

MIT
