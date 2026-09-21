# Agent Relay

Agent Relay is an asynchronous task coordination service for distributed agents. Agents register identities, submit tasks to target agents, claim assigned tasks from an inbox queue, send periodic heartbeats while working, and report execution results or errors.

This repository is an extension of the DataTalksClub AI Dev Tools Zoomcamp Agent Relay starter project. It extends the original SQLite implementation with PostgreSQL persistence and concurrency controls, containerization with Docker and Docker Compose, Kubernetes manifests for Kind clusters, integration test coverage, and an automated GitHub Actions CI/CD pipeline supported locally via `act`.

## Architecture

```
                 +-------------------+
                 |   Client / CLI    |
                 +---------+---------+
                           |
                     HTTP  |  (REST)
                           v
+----------+      +-------------------+      +----------+
| Worker 1 | <--> |  FastAPI Relay    | <--> | Worker 2 |
+----------+      +---------+---------+      +----------+
                            |
                   SQLAlchemy / psycopg
                            v
                  +-------------------+
                  |    PostgreSQL     |
                  +-------------------+
```

- **FastAPI HTTP API (`main.py`, `schemas.py`)**: Exposes REST endpoints for identity registration, task submission, claiming, heartbeats, and status reporting. Relay is the single component with database access.
- **PostgreSQL Database (`database.py`, `storage.py`)**: Stores agents, tasks, and attempt records. Uses PostgreSQL `FOR UPDATE SKIP LOCKED` to allow multiple worker processes to claim tasks concurrently without collisions.
- **Workers (`worker.py`)**: External worker processes that communicate exclusively with Relay over HTTP using token authentication.

## Task Lifecycle

Tasks transition through three states:

1. **`queued`**: A task is submitted via `POST /api/v1/tasks` with a recipient agent ID and input payload.
2. **`processing`**: An assigned worker claims the task via `POST /api/v1/tasks/claim`. A lease duration (`RELAY_LEASE_SECONDS`, default 60s) is assigned. The worker sends heartbeats (`POST /api/v1/tasks/{task_id}/attempts/{attempt_id}/heartbeat`) to keep the lease active.
3. **`completed` / `failed`**: The worker reports completion (`.../complete`) or failure (`.../fail`) along with its claim token. Repeated submissions with the same claim token are idempotent. If a lease expires without a heartbeat, the task returns to the queue up to `RELAY_MAX_ATTEMPTS`.

## Project Structure

```text
.
├── .github/workflows/
│   └── ci.yml                 # CI/CD pipeline definition
├── k8s/                       # Kubernetes manifests for Kind deployment
│   ├── postgres-configmap.yaml
│   ├── postgres-secret.yaml
│   ├── postgres-pvc.yaml
│   ├── postgres-deployment.yaml
│   ├── postgres-service.yaml
│   ├── relay-deployment.yaml
│   └── relay-service.yaml
├── .actrc                     # Runner image configuration for act
├── docker-compose.yml         # Multi-container PostgreSQL and Relay setup
├── Dockerfile                 # Container build definition for Relay
├── database.py                # SQLAlchemy models, engine setup, and schema init
├── storage.py                 # Queue operations, row locking, and state transitions
├── main.py                    # FastAPI application routes, lifecycle, and CLI
├── schemas.py                 # Pydantic request and response schemas
├── worker.py                  # Worker polling implementation
├── test_agent_relay.py        # Protocol, concurrency, and lease tests
├── test_acceptance_scenario_1.py # End-to-end integration and worker flow test
└── pyproject.toml / uv.lock   # Dependencies and locked environments
```

## Local Development (uv)

Prerequisites: Python 3.11+, `uv`.

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Run the Relay API server:
   ```bash
   # Using SQLite (default for local development)
   uv run uvicorn main:app --reload

   # Or using a local PostgreSQL instance
   export RELAY_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/agent_relay"
   uv run python -c "from database import init_db; init_db()"
   uv run uvicorn main:app --reload
   ```

3. Run a worker process:
   ```bash
   uv run python main.py worker \
     --base-url http://127.0.0.1:8000 \
     --name uppercase \
     --worker-id worker-1
   ```

## Docker Compose

Run the complete stack (PostgreSQL and Relay) in Docker:

```bash
# Start services
docker compose up -d --build

# View service logs
docker compose logs -f

# Check container status
docker compose ps

# Stop and remove containers and volumes
docker compose down -v
```

The Relay API is accessible at `http://localhost:8000`.

## Kubernetes (Kind)

Prerequisites: `kubectl`, `kind`, and `docker`.

1. Create a Kind cluster:
   ```bash
   kind create cluster --name agent-relay
   ```

2. Build and load the Relay image into the cluster:
   ```bash
   docker build -t agent-relay-relay:latest .
   kind load docker-image agent-relay-relay:latest --name agent-relay
   ```

3. Deploy PostgreSQL and Relay manifests:
   ```bash
   kubectl apply -f k8s/
   ```

4. Wait for rollouts to finish:
   ```bash
   kubectl rollout status deployment/postgres --timeout=120s
   kubectl rollout status deployment/relay --timeout=120s
   ```

5. Forward the service port to test locally:
   ```bash
   kubectl port-forward svc/relay 8000:8000
   ```

## Testing

Run the automated test suite using `uv`:

```bash
# Runs test_agent_relay.py and test_acceptance_scenario_1.py
uv run pytest -v
```

To run tests against PostgreSQL instead of SQLite:
```bash
export RELAY_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/agent_relay"
uv run python -c "from database import init_db; init_db()"
uv run pytest -v
```

The test suite covers:
- Agent registration and bearer token authentication
- Task claim boundaries and concurrent access guarantees (`FOR UPDATE SKIP LOCKED`)
- Lease expiration and attempt increment logic
- Idempotent completion and failure reporting
- Full end-to-end integration workflow with active workers (`test_acceptance_scenario_1.py`)

## CI/CD Workflow

The GitHub Actions workflow is defined in `.github/workflows/ci.yml`.

### Pipeline Flow

1. **Test (`test`)**:
   - Spins up a `postgres:16-alpine` service container.
   - Installs `uv` and synchronizes project dependencies (`uv sync --frozen`).
   - Verifies database connectivity and initializes the schema.
   - Runs `uv run pytest -v`. If any test fails, the job terminates and prevents deployment.
2. **Build and Deploy (`build-and-deploy`, requires `test`)**:
   - Generates a unique image tag: `agent-relay-relay:v-<short_sha>-<run_number>-<timestamp>`.
   - Builds the Docker image with the unique tag.
   - Loads the image into the Kind cluster (`agent-relay`).
   - Applies the manifests in `k8s/`.
   - Deploys the new image using `kubectl set image deployment/relay relay=agent-relay-relay:<tag>`.
   - Waits for rollout completion (`kubectl rollout status`) and verifies running pod image versions.

### Running CI Locally with `act`

The workflow supports local execution using `act`:

```bash
act --pull=false
```

`.actrc` configures the `ubuntu-latest` runner image to `ghcr.io/catthehacker/ubuntu:act-latest`, providing the required local tooling and Docker CLI environment for executing the workflow under `act`.

## Security

- Agent tokens and database credentials must never be committed to version control.
- The included `k8s/postgres-secret.yaml` manifest is provided for local Kind development and testing; production environments should inject credentials via an external secrets manager or KMS rather than static repository manifests.
- Worker credentials generated locally (`*-credentials.json`) contain bearer tokens and are excluded via `.gitignore`.
