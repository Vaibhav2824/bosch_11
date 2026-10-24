# Incident Zero: quick setup (Windows, PowerShell)

Needs Docker Desktop, Python 3.11, Node 20, uv.

1. Start the demo: in `opentelemetry-demo/`
   `docker compose --env-file .env --env-file .env.override -f compose.yaml -f compose.observability.yaml -f compose.extras.yaml up -d`
   (or `make start` where make exists). Wait until http://localhost:8080 loads.
2. In `oncall/`:
   ```
   uv venv -p 3.11 .venv
   uv pip install -p .venv\Scripts\python.exe -r requirements.txt
   copy .env.example .env      # then paste your GEMINI_API_KEY into .env
   cd web; npm install --legacy-peer-deps; npm run build; cd ..
   $env:PYTHONUTF8 = '1'
   .\.venv\Scripts\python.exe -m oncall_agent check      # all OK?
   .\.venv\Scripts\python.exe -m oncall_agent baseline   # once, while healthy
   ```
3. Two terminals in `oncall/` (both with `$env:PYTHONUTF8 = '1'`):
   - `.\.venv\Scripts\python.exe action_api.py`   (Action API stand-in, :8090)
   - `.\.venv\Scripts\python.exe -m incident_ui`  (UI, http://127.0.0.1:8502)
4. Demo: `.\.venv\Scripts\python.exe simfault.py stop product-catalog`, wait ~90 s,
   type an alert in the UI, approve, watch "Act & verify". Always finish with
   `.\.venv\Scripts\python.exe simfault.py reset`.

Dashboards: Jaeger http://localhost:8080/jaeger/ui, Grafana http://localhost:8080/grafana,
Prometheus http://localhost:9090, Locust http://localhost:8080/loadgen.
See `oncall/UI_README.md` for the UI, Action API and verification details.
