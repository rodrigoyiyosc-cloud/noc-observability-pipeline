# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An end-to-end, multi-region NOC (Network Operations Center) observability pipeline, 100% containerized and driven by Infrastructure as Code. Three regional simulators generate synthetic network telemetry into TimescaleDB; Grafana alerts on it; a FastAPI webhook service deduplicates and escalates incidents to Jira; an `IsolationForest` model (Jupyter) detects anomalies standard thresholds miss; and a LangGraph multi-agent system (NOC-MAS) lets an operator diagnose/act on incidents conversationally via a Streamlit ChatOps UI. See [README.md](README.md) for the full narrative (in Spanish) — it is generally accurate but has some drift from the code; see "README vs. code drift" below before trusting its Roadmap section.

## Architecture

Five layers, one `docker compose up`, all on a shared bridge network `noc_net`:

1. **Simulation** (`python-simulator/`) — 3 regional simulator containers (`simulator-us-east`, `simulator-eu-west`, `simulator-sa-south`), same image, differing only in `REGION` env var. `simulator.py` is the CLI/loop entrypoint; `config.py` holds per-region device topology (`_REGION_SEEDS`); `log_builder.py`/`metrics.py` generate records; `writer.py` handles pluggable sinks (`csv`, `jsonl`, `postgres`). `simulator.py` uses flat imports (`from config import DEVICES`), so it must be run **from inside** `python-simulator/`. Also here: `force_alert_test.py` (deterministic sustained-CRITICAL injector) and `ml_continuous_simulator.py` (Fase 5: continuous multi-region loop that bypasses Grafana's alert evaluation and POSTs `firing`/`resolved` directly to the webhook, producing a perfectly-aligned telemetry↔incident dataset for ML training/dashboards; supersedes/merges `simulate_mttr_incidents.py`'s behavior).

2. **Storage** — TimescaleDB (PG16). Hypertable `network_telemetry` (1-day chunks, `region` in `compress_segmentby`, 7-day compression, 90-day retention). Dimension table `devices`. Schema in `sql/schema.sql`, reference queries in `sql/panels.sql` / `sql/panels_postmortem.sql`, postmortem JSONB views in `sql/incident_views.sql`.

3. **Visualization** — Grafana OSS (Unified Alerting), 100% provisioned via `grafana/provisioning/` (datasources, dashboards, alert rules, contact points, notification policies, mute timings). No manual UI configuration — every change belongs in these YAML/JSON files.

3.5. **ML Analytics Hub** (`jupyter/`) — Jupyter container on `noc_net`, connected directly to TimescaleDB. Notebooks (`IsolationForest.ipynb`, `RandomForest2.ipynb`) train/validate anomaly-detection models on `cpu_pct`/`latency_ms`. Complements, does not replace, Grafana's static thresholds.

4. **Decision layer** (`webhook_service/`) — FastAPI app (`main.py`, run from within `webhook_service/` so `from src...` imports resolve; Docker `WORKDIR /app` mirrors this):
   - `POST /alert` (Bearer-auth via `NOC_WEBHOOK_TOKEN`, `secrets.compare_digest`): persists every alert to `incident_logs` (JSONB), then runs **JQL-based dedup** (`handle_jira_dedup`) — searches `POST /rest/api/3/search/jql` (the classic `/rest/api/3/search` is retired by Atlassian, returns `410 Gone`) by `al-<alertname>`/`dev-<hostname>` labels. Open ticket + `firing` → comment "persists"; open ticket + `resolved` → comment + attempt transition to `JIRA_RESOLVE_TRANSITION_NAME`; no open ticket + `firing` → create ticket with fingerprint labels.
   - `POST /api/chat`: invokes the compiled NOC-MAS `orchestrator` (LangGraph), keyed by `thread_id` via `MemorySaver` checkpointer. **This is already wired up** — not a stub (see drift note below).
   - `GET /health`.
   - **NOC-MAS graph** (`webhook_service/src/`): `state.py` defines `NOCState` (TypedDict; `messages` accumulates via `operator.add`). `orchestrator.py` builds a `StateGraph` with a **Supervisor** node (`ChatGroq`, PTCF prompt, output forced through `PydanticOutputParser`/`RouteResponse`) that routes to `Data_Agent`, `Action_Agent`, `Responder_Agent`, `human_in_the_loop`, or `END`. `src/nodes/data_agent.py` — Text-to-SQL restricted to `SELECT` on `network_telemetry` (regex-blocks DML/DDL, forces table reference, `LIMIT 200`). `src/nodes/action_agent.py` — emits structured `ActionResponse` (`CREATE_TICKET`/`SEND_ALERT`/`ACK_ALERT`/`ESCALATE`/`INFO_QUERY`) and actually executes Jira calls for `CREATE_TICKET`/`INFO_QUERY`. `src/nodes/responder_agent.py` — synthesizes SQL/action results into a short natural-language reply for the operator; ends the graph. HITL safety gate: graph compiles with `interrupt_before=["human_in_the_loop"]`; any P1 severity, irreversible action, or Supervisor parse failure routes there. Every LLM-facing chain strips `<think>...</think>` reasoning blocks (`clean_think_tags`/`strip_think_tags`) before Pydantic parsing, with a safe fallback to `human_in_the_loop` (or a controlled message in the Responder) on failure — these models are served via Groq and can emit raw reasoning traces.

5. **Escalation & ops** (`chatops_ui/`) — Streamlit app (`app.py`) calling the webhook service's `/api/chat` over the internal Docker network (`http://webhook-service:8000/api/chat`), with a per-browser-session `thread_id` (`st.session_state`) so LangGraph memory persists across turns. Sidebar connectivity/metrics widgets are currently hardcoded display values, not live-wired.

### README vs. code drift

The README (v5.0, Roadmap "Fase 6") describes the ChatOps UI as still in *standalone mode*, not yet calling the real orchestrator. That is stale — `chatops_ui/app.py` already POSTs to `/api/chat` and renders the real reply, `next_agent`, and HITL flag. The README's file tree also shows `webhook_service/src/main.py`; in the actual tree `main.py` lives at `webhook_service/main.py` (top level), with `src/` holding only `state.py`, `orchestrator.py`, `nodes/`. The README also doesn't mention the `Responder_Agent` node (`src/nodes/responder_agent.py`) or `python-simulator/ml_continuous_simulator.py`, both of which exist in code. Trust the code over the README's Roadmap/file-tree sections; the architecture narrative and setup/troubleshooting sections are otherwise accurate.

### `tests/`

`tests/test_supervisor.py` and `tests/test_action_agent.py` are **manual verification scripts**, not an automated pytest suite — they print results rather than assert, and they import via `webhook_service.src...` (i.e. expect to run from the repo root, unlike `main.py` itself which expects `webhook_service/` as cwd). Run them directly with `python`, not `pytest`, and expect them to hit the real Groq/Jira APIs (they need `GROQ_API_KEY`/Jira env vars loaded, e.g. via a `.env` next to them or `python-dotenv`).

## Commands

All commands assume PowerShell on Windows (see README §Requisitos/§Instalación for the canonical, verified sequence).

```powershell
# Bring up all 9 services (3 simulators, TimescaleDB, Grafana, webhook service w/ embedded NOC-MAS, Jupyter, ChatOps UI)
docker compose up -d --build
docker compose ps

# Initialize schema (run once, in order, after first startup)
Get-Content sql/schema.sql | docker exec -i timescaledb psql -U noc_user -d noc
Get-Content webhook_service/webhook_service.sql | docker exec -i timescaledb psql -U noc_user -d noc
Get-Content sql/incident_views.sql | docker exec -i timescaledb psql -U noc_user -d noc

# Redeploy after a code/config change
docker compose down
docker compose up -d --build

# Tail webhook service logs (Jira/Supervisor/dedup diagnostics)
docker logs webhook_service --tail 50

# Run a regional simulator manually (must cd into python-simulator/ first — flat imports)
cd python-simulator
$env:REGION = "eu-west"
python simulator.py --fmt postgres --interval 2 --batch 3 --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"

# Force an end-to-end alert (telemetry -> Grafana -> webhook -> Jira dedup)
python force_alert_test.py --minutes 5 --pg-dsn "postgresql://noc_user:secret@localhost:5432/noc"

# Populate ML training data / trigger synced incidents (bypasses Grafana alert evaluation)
python ml_continuous_simulator.py --webhook-url "http://localhost:8000/alert"

# Manual verification scripts for the NOC-MAS graph (run from repo root; needs GROQ_API_KEY/Jira env vars)
python tests/test_supervisor.py
python tests/test_action_agent.py

# Invoke the orchestrator directly inside the running container
docker exec -it webhook_service python -c "from src.orchestrator import orchestrator; ..."
```

There is no linter, formatter, or automated test runner configured (no `pytest.ini`/`pyproject.toml`, no CI). Validate changes by exercising the running services (`docker compose up`, then hit `/health`, `/alert`, `/api/chat`, or the Grafana/Streamlit UIs) — see README §Troubleshooting for common failure modes and their log signatures (Jira `410 Gone` on the old search endpoint, `401` from a token mismatch between `.env` and `contact_points.yml`, Supervisor falling back to `human_in_the_loop` due to unparseable LLM output, etc.).

## Key environment variables

Defined in `.env` at repo root (gitignored; `docker-compose.yml` and each service's `env_file`/`environment` block reference these). Notably: `NOC_WEBHOOK_TOKEN` (required — service refuses to start without it), `JIRA_URL`/`JIRA_USER`/`JIRA_API_TOKEN`/`JIRA_PROJECT_KEY`/`JIRA_RESOLVE_TRANSITION_NAME`/`JIRA_ISSUE_TYPE` (optional — dedup degrades to `{"action": "skipped", "reason": "missing_credentials"}` without them), `GROQ_API_KEY` + `NOC_SUPERVISOR_MODEL`/`NOC_DATA_AGENT_MODEL`/`NOC_ACTION_AGENT_MODEL`/`NOC_RESPONDER_AGENT_MODEL` (NOC-MAS LLM config, default model `openai/gpt-oss-20b` via Groq), `PG_DSN` (read path for Data Agent + Jupyter), `JUPYTER_TOKEN`, `WEBHOOK_URL` (used by simulator scripts).

## Working in this repo

- This is an Infrastructure-as-Code project: alert rules, dashboards, datasources, maintenance windows, and the NOC-MAS graph topology are all meant to live in versioned files (`grafana/provisioning/`, `sql/`, `webhook_service/src/orchestrator.py`), not configured by hand through a UI.
- The Data Agent's SQL sandboxing (`_validate_query` in `data_agent.py`) is a deliberate security boundary — SELECT-only, single-table, regex-blocked DML/DDL, row-limited. Don't loosen it without treating it as a security-relevant change.
- Every Groq-backed LLM chain in the NOC-MAS strips `<think>` blocks before Pydantic parsing and has an explicit fallback path (usually `human_in_the_loop`, or a controlled user-facing message in the Responder). Preserve that pattern in any new agent/node.
