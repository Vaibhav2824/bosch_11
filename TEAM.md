# Team form

**Team:** BOSCH Team 11
**Event:** Incident Zero: Build an AI On-Call Engineer (Bosch × PES University, 23–24 Oct 2026)

## Members and who built which part

| Member | GitHub | Built |
|---|---|---|
| Vaibhav | [@Vaibhav2824](https://github.com/Vaibhav2824) | Repo setup (uv, ruff, pytest, CI), package skeleton, synthetic practice bundles, project README, ran the live demo |
| Adithya Shetty | [@Blu-cheese](https://github.com/Blu-cheese) | `oncall_agent/`: telemetry tools, agent loop, evidence checks, reports, detector; `simfault.py`; Action API safety (kill switch, telemetry-stack denylist) |
| Harshini Somangali | [@h-a-r-s-h-i-n-i-s-o-m-a-n-g-a-l-i](https://github.com/h-a-r-s-h-i-n-i-s-o-m-a-n-g-a-l-i) | Provisional incident schema, offline bundles, `eval/practice.yaml`, incident reports |
| Sharvari | [@sharram](https://github.com/sharram) | Diagnosis module, LangGraph workflow, prompts and LLM wrapper; agent step-budget fix |
| Ananya | [@Ananyajc123](https://github.com/Ananyajc123) | Incident pipeline prototype; `container_health` ranking fix |

Approval UI (`incident_ui/`, `web/`) and Action API (`action_api.py`): built by **FILL IN**.

## AI models used

| Where | Model |
|---|---|
| Agent at runtime | Gemini 3 Flash (`gemini/gemini-3-flash-preview`) via LiteLLM |
| Tried on Day 1, dropped | Groq `openai/gpt-oss-120b` (the free tier's 8K tokens/min limit was too low) |

## AI coding assistants used

- Claude (Anthropic): used for code, debugging and documentation.
- FILL IN any others the team used (ChatGPT, Copilot, Cursor, …).

## Third-party libraries and tools

**Python:** litellm, requests, pydantic, mcp (optional dependency of litellm), pytest, ruff, uv. The `src/oncall` package also lists langgraph, langchain-groq, httpx, drain3 and pyyaml.

**Web UI:** React 19, TypeScript, Vite, Tailwind CSS 4, SmoothUI components, Base UI, motion, lucide-react, clsx, tailwind-merge, class-variance-authority, oxlint.

**Infrastructure:** OpenTelemetry Demo (Astronomy Shop) on Docker Compose, Prometheus, Jaeger, OpenSearch, Locust, and `nicolaka/netshoot` (for the latency fault in `simfault.py`).
