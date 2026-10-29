# API Reference

The paths below are served by the local FastAPI adapter at `http://127.0.0.1:8000` and by the optional API Gateway/Lambda target when separately deployed. Protected cloud requests require a Cognito access token in the `Authorization: Bearer` header. The cloud handler ignores body-supplied actor identity and derives the actor from validated JWT claims. Local demo routes use fixed synthetic IDs and are not secure authentication.

## Donation endpoints

| Method/path | Purpose | Authorization |
|---|---|---|
| `GET /api/health` | Health/status indicator | Public |
| `GET /api/donations` | Bounded available listings | Local may accept `actor_id`/role for demo behavior; cloud requires a recognized group |
| `GET /api/donations/page?status=available&limit=25&cursor=...` | Status page; maximum page size 100 | Non-admin can request available only; admin may query lifecycle status |
| `GET /api/donations/mine?limit=25&cursor=...` | Donor's listings or recipient's own claims | Donor/recipient; local identity is query parameter, cloud identity is JWT |
| `POST /api/donations` | Create listing | Donor; cloud donor ID comes from token |
| `PATCH /api/donations/{id}` | Edit fields while available | Owning donor |
| `POST /api/donations/{id}/claim` | Atomically claim an available, unexpired listing | Recipient/NGO |
| `PATCH /api/donations/{id}/status` | Cancel an available listing or confirm claimed pickup | Owning donor for cancel; claiming recipient for pickup |
| `GET /api/donations/{id}/events?limit=25&cursor=...` | Chronological donation activity page | Participant or administrator |
| `GET /api/me?actor_id=...` | Local synthetic profile lookup | Local demo profile only; not a production identity endpoint |
| `GET /api/me/dashboard?actor_id=...` | Backend-derived counts, completed quantities, recent records/events, and upcoming pickups scoped to the authenticated donor or NGO; global available count is a marketplace summary | Local demo uses the `actor_id` query parameter; cloud adapter derives identity and role from Cognito JWT claims |

Creation/edit fields: `food_name`, `description`, `category`, positive `quantity`, `unit`, optional timezone-aware `available_at`, future timezone-aware `pickup_deadline`, and `pickup_location`. The local adapter accepts synthetic `donor_id` / `actor_id` / `ngo_id` fields to select the fixed demo identity. Cloud API requests must not send trusted actor IDs; ownership is derived from claims.

## Administrator routes

| Method/path | Purpose | Authorization |
|---|---|---|
| `GET /api/admin/analytics` | Filtered donation metrics | Admin |
| `GET /api/admin/donations` | Local admin donation list | Local demo admin only |
| `GET /api/admin/export` | Admin export | Admin; cloud export is bounded to 500 records |
| `POST /api/admin/expire` | Process due records in a bounded batch | Admin |
| `GET /api/admin/users?search=&status=&limit=25&cursor=` | Search/paginate synthetic profiles | Local demo admin only |
| `PATCH /api/admin/users/{id}/status` | Suspend/reactivate a synthetic profile | Local demo admin only; self-status changes are refused |
| `GET /api/admin/users/{id}/events` | Local synthetic account activity | Local demo admin only |
| `GET /api/admin/activity` | Filtered, cursor-paginated local audit history | Local demo admin only |
| `GET /api/admin/etl/runs` | In-process local ETL run history | Local demo admin only |
| `POST /api/admin/etl/runs` | Export current local records and run the actual Pandas ETL pipeline | Local demo admin only; synchronous and single-run guarded |
| `GET /api/admin/etl/runs/{run_id}/reports/{report_name}` | Download an allow-listed report from a successful local ETL run | Local demo admin only |
| `GET /api/admin/system/health` | Check local SQLite connectivity and expose explicit CI/deployment unknown/not-deployed states | Local demo admin only |

Analytics filters: `start_date`, `end_date` in valid `YYYY-MM-DD` form, `status`, `category`, and `location`. Start must not be after end. Cloud analytics route validates filters and queries at most 500 records; user-count fields are `null` because cloud profile administration is not implemented.

The dashboard uses current repository state, does not return records owned by another user, and groups completed quantities by their original unit. The cloud adapter derives identity from verified Cognito claims, uses indexed DynamoDB queries, and bounds each donation query to 500 records; it returns 503 if that bound is exceeded. Recent cloud activity is gathered from the five most recently created owned donations. The local demo uses SQLite and the supplied synthetic `actor_id`.

## Responses, errors, pagination

- Success responses are JSON. Creation returns HTTP 201; other successful transitions return 200.
- In the cloud adapter, `401` means no valid authorized identity; `403` means authenticated but role/ownership is insufficient. The local demo adapter rejects unknown/suspended profiles with `403` and malformed/missing request fields with `422`. `404` means the target is missing; `409` means stale/invalid state or competing claim; `503` indicates a temporary/configuration/storage failure.
- List responses that support pagination use `{ "items": [...], "next_cursor": "..." }`. Treat cursors as opaque; request the next page with the returned cursor. Maximum limit is 100.
- Local middleware returns `X-Request-ID`. AWS Lambda records the API Gateway/Lambda request ID in audit events where supported.

FastAPI's OpenAPI/Swagger UI is available at `/docs` when the local backend is running. It documents the local adapter, not proof of the deployed AWS API contract.
