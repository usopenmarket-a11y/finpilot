# Bank sync operations

The Settings page starts sync jobs through `/api/v1/accounts/sync/*` and polls
`/api/v1/accounts/sync/status/{job_id}`. NBE, CIB, BDC Kony (`BDC_RETAIL`), and UB
are in the API dispatch table. CIB's live scraper currently fails fast because
its portal blocks automated access; a saved CIB credential does not make live
sync available. Account, credit card, certificate, loan, and prepaid endpoints
are available where each scraper supports that data.

Only one scrape runs at a time in the API process. The job starts quickly and
the UI polls while the browser continues in the background. The API keeps
active job state in memory and writes snapshots to the `sync_jobs` table.
Restarting the container can still interrupt a running browser. Run one API
container and avoid deployments during an active sync. If scraping succeeds
but saving to Supabase fails, the job reports `failed` and does not advance
the credential's `last_synced_at` timestamp.

### Time limits

The API stops any scrape that exceeds its job type's deadline, closes the
browser, and reports `Bank portal timed out`, which frees the single scrape
slot for the next request:

| Job type | Server deadline | Browser polling limit |
| --- | --- | --- |
| Full sync | 40 min | 45 min |
| NBE accounts | 35 min | 40 min |
| NBE cards, certificates, loans, prepaid | 15 min each | 20 min |

The deadlines come from recorded `sync_jobs` durations on the old Render host,
where successful NBE account runs took up to about 31 minutes. The values live
in `_PHASE_DEADLINE_S` (`apps/api/app/routers/sync.py`) and
`SYNC_CLIENT_WAIT_MS` (`apps/web/src/lib/api-client.ts`); change both together
and keep the browser limit longer. Browser teardown is bounded as well, so a
stuck Chromium cannot hold the slot.

If the API restarts during a sync, a later status poll marks that job
`failed` with an "interrupted" message instead of reporting `running`
indefinitely. NBE "Sync all" runs every product phase even when one fails and
then lists the phases that need a retry.

The daily scheduler code exists in `apps/api/app/scheduler.py` but is not
started by `apps/api/app/main.py`. Automatic daily sync is currently disabled.

## BDC production proxy

The current BDC Kony scraper requires an Egyptian HTTP(S) proxy whenever
`APP_ENV=production`, including on a Kali host. Put the proxy URL and optional
authentication in `apps/api/.env`:

```dotenv
BDC_PROXY_SERVER=http://proxy.example:12321
BDC_PROXY_USERNAME=your-provider-username
BDC_PROXY_PASSWORD=your-egypt-sticky-session-password
```

Select an Egyptian exit and a sticky session of at least 30 minutes at the
provider. The URL must contain an explicit port and no embedded credentials.
Both authentication fields may be empty for an IP-authenticated proxy. Keep
all three variables on the API service, never in `NEXT_PUBLIC_*` or Git.
The scraper does not fall back to a direct connection if a required proxy is
missing or fails. Local development without `APP_ENV=production` permits a
direct connection.

To check routing without bank credentials, run the preflight inside the API
container after configuration:

```sh
docker compose -f compose.prod.yml exec api python -m app.bdc_preflight
```

For the existing-proxy deployment, add
`-f compose.prod.existing-proxy.yml` to the command. The preflight checks the
Egyptian exit, BDC login form, and exit IP stability. It does not authenticate
or write bank data. A passing preflight does not prove a full sync works.

The Kony scraper captures account balances, credit card details, and each
credit card's transaction history (checked against the portal on 2026-09-26).
It does not capture deposit account transactions; the tested login has only a
zero-balance placeholder account.

- The portal sometimes resets the connection for its main app script or
  stalls before showing the login form. The scraper reloads the page up to
  three times (about 40 s each) and then reports a portal timeout, not
  invalid credentials.
- The redesigned login page records the password from key events, so the
  scraper types it key by key and stops if the field did not receive it.
- Each login form step has a 15 s limit. If a step before Sign In times out,
  the scraper reloads the portal and fills the form once more; nothing has
  been submitted at that point. A Sign In click that times out falls back to
  the button's own handler. The API log names the step that timed out.
- A card's `balance` is the amount owed: `utilizedAmount + holdAmount`
  (approved limit minus available credit). The portal's `outstandingBalance`
  equals the available credit and is not used.
- History comes from `BDC_CardsManagement/.../getCreditTransactionsHistory`
  in one response. The call needs `Content-Type: application/json`; with a
  form content type it returns an empty list and HTTP 200. The scraper first
  calls `getAllActiveCards`, as the portal's Cards page does; without it the
  first history call of a session stalled past the request timeout. A failed
  history call is retried once.
- Foreign purchases are stored in the billed EGP amount (`AmountAcct`), with
  the original amount and currency in `raw_data`. Declined rows are skipped.
- Rows are keyed by the bank transaction ID (`bdc:<Id>`), so re-syncs update
  rows in place. The full card number is sent to the portal only; it is never
  stored in `raw_data` or logged.

Card history from the retired T24 portal (`raw_data.source = 'bdc_retail'`)
used different transaction keys, so those rows duplicate the same purchases
in the new history.

Each API call has a bounded request timeout. A failed account, card, or card
history call fails the full scrape instead of silently reporting partial
data. An empty card history is logged as a warning.

## NBE account types

The accounts widget's Arabic product name is stored as `product_name` and
mapped to an account type. A debit-current row (`جاري مدين`, e.g. an
overdraft secured against certificates) is stored as `loan` with the drawn
amount as a positive balance owed; the portal shows it as negative. The
dashboard counts `loan` accounts as liabilities.

An NBE certificate can share its last four digits with the account it was
opened from. When one scrape returns both, transactions go only to the
non-certificate account.

## NBE credit card history

The pipeline replaces fetched NBE unbilled, unsettled, and statement sections
instead of accumulating stale rows. The September database migration adds an
atomic replacement RPC. If a scraper section is missing or empty, existing
history is retained. Apply that migration before deploying the paired API
changes; see [database.md](database.md).

## Diagnostics

```sh
docker compose -f compose.prod.yml ps
docker compose -f compose.prod.yml logs --tail=150 api
curl -fsS https://<SITE_DOMAIN>/api/v1/health
```

Use the two-file Compose command for `ps` and `logs` when an existing reverse
proxy is in use. Check the job status response and API logs first. Avoid
logging or uploading bank pages, credentials, raw tokens, and personal account
screenshots while troubleshooting.
