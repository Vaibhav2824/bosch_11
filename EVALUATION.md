# Evaluation note

Which practice incidents our agent got right and wrong in our own testing, and why.

## How we tested

- **Setup:** OpenTelemetry Demo in minimal mode (no Kafka) on an 8 GB M2 MacBook Air, Locust at 5 users.
- **Faults:** injected with `simfault.py`, our dev stand-in for faultctl. It uses Docker only and never touches feature flags.
- **Agent:** Gemini 3 Flash (`gemini/gemini-3-flash-preview`) through LiteLLM. Budget: 8 tool steps plus 2 steps where only `submit_diagnosis` is allowed.
- **Alert:** a generic alert was given to the agent. It was never told which fault was injected.
- **Correct** means the diagnosed component and cause match the injected fault. An escalation is counted as safe, but not as correct.

Full outputs for every Day 2 run are in [`reports/`](reports/). Each folder holds `diagnosis.json` (our JSON schema), `report.md` (readable report), `evidence.jsonl` and `transcript.jsonl`.

## Day 2 results

| Run (`reports/…`) | Alert given | Injected fault | Agent result | Confidence | Verdict |
|---|---|---|---|---|---|
| `20261024-132406` | error rate above threshold on the shop | product-catalog container down | Diagnosed **product-catalog exited**, proposed `restart_service product-catalog` | 0.80 (containers + traces) | ✅ Correct |
| `20261024-140618` | error rate above threshold on the shop | product-catalog container down | Diagnosed **product-catalog exited** (gRPC UNAVAILABLE / connection refused), `restart_service` | 0.80 (containers + traces) | ✅ Correct |
| `20261024-140833` | error rate above threshold on the shop | product-catalog container down | Diagnosed **product-catalog exited**, 0 rps vs 5.23 baseline, `restart_service` | 0.95 (containers + metrics + traces) | ✅ Correct |
| `20261024-141451` | error rate above threshold on the shop | product-catalog container down | Diagnosed **product-catalog exited**, `restart_service` | 0.80 (containers + traces) | ✅ Correct |
| `20261024-142554` | "error alert" | not recorded (errors on cart / checkout / frontend) | **Escalated**: did not converge | 0.00 | ⚠️ Safe escalation, not a diagnosis |
| `20261024-143057` | "cpu starved" | CPU starvation (`simfault cpu`) | **Escalated**: did not converge | 0.00 | ⚠️ Safe escalation, not a diagnosis |

**Score: 4 of 6 correct and 2 safe escalations. No confident wrong fix was proposed.** Each of the four correct runs took 14 to 24 seconds.

## Why the two escalations failed

Both runs used all 10 steps on tool calls and never called `submit_diagnosis`. The transcripts show tool calls at steps 9 and 10. The cause was a bug in the agent loop: `last = step == MAX_STEPS` was true only on step 8, so steps 9 and 10 offered every tool again instead of only `submit_diagnosis`. This was fixed in commit `edbe543` (`last = step >= MAX_STEPS`). Both incidents have not yet been re-run with the fix.

The CPU-starvation run had a second weakness. The agent called `container_health` on six different services, including `accounting` and `otelcol-contrib`, which don't run in minimal mode. It never found a strong CPU signal. `container_health` reports `cpu_limit` and `cpu_pct`, but the prompt doesn't tell the agent to compare them, so a throttled container doesn't stand out.

## Day 1 results (before the reports folder existed)

| Situation | Agent result | Verdict | What we changed |
|---|---|---|---|
| product-catalog OOM-killed (real, caused by the 20 MiB demo limit) | Diagnosed product-catalog, confidence 0.8, `restart_service` | ✅ Correct | – |
| product-catalog down, Groq `gpt-oss-120b` | Right investigation path, then hit Groq's 8K tokens/min limit and could not submit | ❌ Did not converge | Switched to Gemini 3 Flash, added rate-limit retries |
| product-catalog down, early quote checker | Right path, final evidence quote rejected over formatting | ❌ Did not converge | Made quote matching accept multi-field quotes |
| paymentFailure 50% while the laptop was overloaded | Diagnosed "frontend exited", confidence 0.95 | ❌ Wrong | Exited containers from other Docker projects were being read. `container_health` now filters to the demo's compose project |

## Calibration

| Stated confidence | Runs | Correct |
|---|---|---|
| 0.95 | 1 | 1 |
| 0.80 | 3 | 3 |
| 0.00 (escalated) | 2 | – |

Confidence is capped by the number of independent sources (1 source → 0.6, 2 → 0.8, 3+ → 0.95). On this small sample, every diagnosis at 0.8 or above was right. The model's own confidence was 1.0 every time, so the source cap is doing the calibrating. Six runs are too few to claim the confidence is well calibrated.

## Known gaps

- Only one fault type, a service container that is down, has been diagnosed reliably on Day 2.
- Feature-flag faults (cart, payment, ad, recommendation) and latency faults were not re-tested on Day 2.
- CPU starvation and network latency are weak spots, because the agent has no clear throttling or latency-between-services signal.
- Kafka-path incidents can't be reproduced in minimal mode.
- On an 8 GB laptop, real out-of-memory kills and hangs can hide or imitate an injected fault.
