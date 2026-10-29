# Synthetic local dataset

ShareBite includes an explicit local-only seed command for repeatable demonstrations. The command creates illustrative data; names and organizations do not imply real users, customers, or partners.

## Create or reuse the seed database

From the project root:

```bash
.venv/bin/python -m backend.seed_data
```

By default this targets `backend/data/sharebite-synthetic.db`. The seed set includes eight donations across available, claimed, picked-up, cancelled, and expired states; multiple food categories, units, and Indian locations; fixed synthetic donor/recipient identities; and lifecycle events linked to each donation.

The command is:

- **Explicit:** it runs only when invoked and is never part of API startup.
- **Idempotent:** rerunning against its own seeded database reports the existing seed count without inserting duplicate records.
- **Fail-closed:** if the target contains tables but lacks the ShareBite seed marker, it refuses to proceed. It does not overwrite or migrate that database.
- **Isolated by default:** it does not target `backend/data/app.db`, which may contain existing user data.

To select an alternate path, use `--database /path/to/empty.sqlite`. The target must be new or an empty SQLite file. Do not point the command at a live or valuable database.

## Run against the seeded database

Terminal 1:

```bash
FOOD_REDISTRIBUTION_DB=backend/data/sharebite-synthetic.db \
APP_MODE=local-demo DONATION_STORE=sqlite \
.venv/bin/uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
VITE_AUTH_MODE=local-demo npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. Switch among the synthetic local identities to exercise donor, recipient, and administrator views. The local identity switcher is a development convenience, not secure authentication; do not use it with real personal data or expose the development server publicly.

## Preservation and cleanup

The checked-in database path `backend/data/app.db` is not used by the seed command. Seed output is ignored by Git because local SQLite files are excluded. If you choose a custom path, remove only that specific disposable file after stopping the API, and only if you are certain it contains no data you need.

The seed command creates consistent relationships and history, but the activity is synthetic. It must not be presented as live platform activity, verified food distribution, or impact evidence.
