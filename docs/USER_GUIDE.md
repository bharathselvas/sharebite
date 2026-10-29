# User Guide

## Product and mode

The ShareBite shell provides donor, recipient, and administrator navigation. A small mode banner distinguishes local synthetic data from an authenticated Cognito application. The local account selector is a workflow simulator and must not be used to protect real data. In Cognito mode, the API derives identity and role from validated authorizer claims. An account with zero or multiple recognized role groups cannot access protected features.

## Donor

- Create a listing with food name, quantity/unit, pickup deadline, category, optional description, and optional location.
- The overview shows backend-derived counts, recently claimed donations, and completed quantities grouped by unit in the local adapter.
- Use **Create donation**, **My donations**, **Claims**, and **Donation history** to focus the listing view. Search, category/location/deadline filters, sorting, and cursor-based load more operate on currently loaded records.
- Edit the listing only while its status is `available`.
- Open donation details and review the recorded event history for a donation you own.
- Cancel an available donation you own.
- A donor cannot claim a different donor's listing or confirm a recipient's pickup.

## Recipient / NGO

- Browse available donations and search/filter the loaded listings by text/status.
- The overview shows the marketplace availability count, active claims, upcoming collections, and completed quantities from the local dashboard endpoint.
- Claim an available, unexpired listing. The backend performs the state transition; a competing claim is rejected.
- Confirm collection only for a listing claimed by the current recipient.
- Open listing details before claiming. Review active claims and collection history. Only a participant or administrator may view a donation's event timeline.

## Administrator

- Start at **Operations Overview** for backend-derived donation KPIs, UTC creation-date filters, donation and status trends, recent recorded activity, the latest local ETL run, and open listings approaching or past their pickup deadlines.
- Refresh reloads the connected application data. KPI links open the corresponding donation status filter; charts and rates are based on the selected analytics population and do not invent comparisons.
- Use **All donations** to scan a responsive operational table with quantity/unit, donor and recipient display names, pickup deadline, lifecycle state, search, filters, sorting, and cursor-based load more. The table scrolls within its own container on narrow screens.
- Review application counts, donation status totals, claim/completion/expiry rates, completed quantity by unit, and average time to claim in **Analytics**. Filters use the existing analytics API and timestamps are grouped in UTC.
- Inspect all donations, event history, local ETL runs/reports, and evidence-based local system health in separate portal pages.
- User management supports local account-name search, role/status filters, activity view, and server-authorized status changes with confirmation. These operations apply only to synthetic SQLite profiles.
- The ETL center clearly identifies its SQLite export source, Pandas transformation, temporary report destination, and synchronous execution. Starting a run requires confirmation; no run is triggered automatically.
- Donation results, user history, and event history provide cursor-based “load more” controls where a next page exists.
- In local-demo mode only, search the fixed synthetic account list and suspend/reactivate local profiles. This does not manage Cognito users.
- Trigger bounded expiry processing. Claims are rejected after deadlines even if a background expiry pass has not run.
- Local chart history and profile counts include synthetic data. Cloud aggregation is capped at 500 donation records and is not suitable for large deployments.

## Status and metric interpretation

Lifecycle: `available -> claimed -> picked_up`. An available listing can instead become `cancelled` or `expired`. Pickup status is an authorized confirmation recorded by the application; it is not independent proof of physical delivery.

- Claim rate = `(claimed + picked_up) / all donations in the selected created-date/category/location population`; choosing a status filter changes the displayed records but not this rate's cohort.
- Completion rate = `picked_up / all donations in that population`.
- Expiry rate = `expired / (picked_up + cancelled + expired)` in that population. An empty denominator displays zero.
- Available count includes only rows in the `available` state whose pickup deadline is still in the future.
- The recipient portal does not offer a claim action when a listing's pickup deadline has passed; the backend remains authoritative and rejects stale claims.
- Redistributed quantity counts only `picked_up` rows and remains separated by the source unit, including daily outputs.
- Average time to claim averages timezone-aware, non-negative `claimed_at - created_at` values; invalid timestamp pairs are excluded.
- Timestamps and daily grouping use UTC. Local admin counts are fixed synthetic profiles. Cloud user counts are unavailable.

Role-specific donor and recipient dashboard counts are computed by the API and scoped to the current account; marketplace availability is global. In cloud mode the API derives account identity from the authenticated Cognito token and uses bounded DynamoDB index queries. Dashboard aggregation returns an unavailable response if a query exceeds the 500-record safety bound.

These are application metrics, not proof of food waste prevented or an environmental impact estimate. Read [ARCHITECTURE.md](../ARCHITECTURE.md) for formulas and bounds.

## Errors and privacy

Validation errors identify a correction; authorization errors mean the account/role/ownership is not permitted; a conflict means the donation state changed or is no longer claimable. Refresh rather than retrying a transition blindly. Do not enter contact details or other sensitive information in demo records. Audit history is an application log, not an immutable ledger.

## Known feature boundaries

- Local account selection is simulated with fixed synthetic identities; it is not a real local authentication system. Create a populated, isolated local dataset with the explicit command in [Synthetic data guide](./SYNTHETIC_DATA_GUIDE.md).
- The signed-in cloud role/short subject is shown in the header, but a full editable user profile page is not implemented.
- Cognito sign-in/registration is only prepared in the optional template/client; no live account was tested. Self-registered cloud accounts require exactly one administrator-assigned role group.
- Cognito user search, role/group administration, suspension/revocation, and cloud user audit workflows are not implemented.
- Local user search/filter/pagination only covers the fixed synthetic profile set. Cloud admin lists/metrics are capped at 500 donations.
- Notification delivery and scheduled expiry are not implemented.
