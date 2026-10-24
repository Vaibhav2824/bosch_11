# Incident report: Alert fired: error rate above threshold on the shop

**Decision:** diagnosed  
**Confidence:** 0.8 (2 independent source(s) -> confidence capped at 0.8)  
**Summary:** The shop is experiencing a high error rate because the product-catalog service has exited, causing gRPC UNAVAILABLE (status 14) errors in the frontend and recommendation services.

## Root cause
**product-catalog**: The product-catalog service container has exited, leading to connection refused errors for all dependent services.

## Evidence
- `ev_4` (traces): "finishConnect(..) failed with error(-111): Connection refused: product-catalog/172.23.0.24:3550". Traces show that downstream services (frontend, recommendation) cannot connect to the product-catalog service.
- `ev_5` (containers): ""status": "exited"". Container health check confirms the product-catalog container has stopped running.
- `ev_5` (containers): ""health": "unhealthy"". The container is marked as unhealthy.

## Log excerpts
- `ev_2` frontend [error] x147: API request failed
- `ev_2` otelcol-contrib [error] x36: Exporting failed. Dropping data.
- `ev_2` load-generator [ERROR] x8: Error in add to cart task: Timeout 15000ms exceeded while waiting for event "response"
=========================== logs ===========================
waiting for event "response"
=======================
- `ev_2` frontend [error] x8: Checkout failed to place order
- `ev_2` otelcol-contrib [error] x1: Error scraping metrics
- `ev_6` product-catalog [INFO] x159: Product Found
- `ev_6` product-catalog [INFO] x41: Found 10 products from database

## Proposed action (needs human approval)
- restart_service product-catalog: The product-catalog service has exited and is no longer responding to requests, causing errors in the frontend and recommendation services.

## Investigation timeline
- 2026-10-24T14:14:53 `ev_1` service_overview {"window": "2m"}
- 2026-10-24T14:14:56 `ev_2` search_logs {"minutes": 10, "level": "error"}
- 2026-10-24T14:14:58 `ev_3` service_detail {"window": "5m", "service": "frontend"}
- 2026-10-24T14:14:59 `ev_4` get_traces {"kind": "errors", "service": "frontend"}
- 2026-10-24T14:15:01 `ev_5` container_health {"service": "product-catalog"}
- 2026-10-24T14:15:03 `ev_6` search_logs {"minutes": 10, "level": "any", "service": "product-catalog"}
- 2026-10-24T08:14:51Z Alert fired: error rate above threshold on the shop
- 2026-10-24T08:44:54Z Frontend logs show 'API request failed' and 'Checkout failed to place order'
- 2026-10-24T08:44:54Z Traces confirm connection refused to product-catalog service
- 2026-10-24T08:45:00Z Container health check confirms product-catalog has exited
