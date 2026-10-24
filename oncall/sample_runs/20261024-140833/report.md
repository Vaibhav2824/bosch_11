# Incident report: Alert fired: error rate above threshold on the shop

**Decision:** diagnosed  
**Confidence:** 0.95 (3 independent source(s) -> confidence capped at 0.95)  
**Summary:** The product-catalog service is down (container exited), causing a 100% error rate in the recommendation service and a significant error rate in the frontend.

## Root cause
**product-catalog**: The product-catalog service container has exited, leading to service unavailability and downstream errors in the recommendation and frontend services.

## Evidence
- `ev_3` (containers): ""service":"product-catalog","status":"exited","health":"unhealthy"". The product-catalog container has exited and is unhealthy.
- `ev_2` (traces): ""error_message":"product-catalog: No address associated with hostname","operation":"oteldemo.ProductCatalogService/ListProducts","origin_service":"recommendation","status_code":"14"". The recommendation service is failing to call the product-catalog service with gRPC status 14 (UNAVAILABLE) because the hostname cannot be resolved, confirming the service is down.
- `ev_1` (metrics): ""service":"product-catalog","rps":0.0,"error_pct":0.0,"p95_ms":null,"baseline":{"rps":5.23,"error_pct":0.0,"p95_ms":1454.0}". The product-catalog service is receiving zero traffic compared to its baseline, consistent with the service being down.

## Log excerpts
- `ev_5` product-catalog [INFO] x158: Product Found
- `ev_5` product-catalog [INFO] x42: Found 10 products from database
- `ev_7` frontend [error] x189: API request failed
- `ev_7` frontend [error] x11: Checkout failed to place order

## Proposed action (needs human approval)
- restart_service product-catalog: The product-catalog container has exited and needs to be restarted to restore service functionality.

## Investigation timeline
- 2026-10-24T14:08:35 `ev_1` service_overview {"window": "2m"}
- 2026-10-24T14:08:37 `ev_2` get_traces {"kind": "errors", "service": "recommendation"}
- 2026-10-24T14:08:39 `ev_3` container_health {"service": "product-catalog"}
- 2026-10-24T14:08:44 `ev_4` container_health {"service": ""}
- 2026-10-24T14:08:46 `ev_5` search_logs {"service": "product-catalog", "level": "any"}
- 2026-10-24T14:08:48 `ev_6` search_logs {"level": "error", "service": "recommendation"}
- 2026-10-24T14:08:49 `ev_7` search_logs {"level": "error", "service": "frontend"}
- 14:08:33 Alert fired: error rate above threshold on the shop
- 14:09:00 Observed 100% error rate in recommendation service and 0 RPS in product-catalog service.
- 14:10:00 Confirmed product-catalog container is in 'exited' state.
