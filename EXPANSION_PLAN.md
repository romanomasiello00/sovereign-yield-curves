# Yield Curve Pipeline — Status & Expansion Plan

_Last updated: 2026-06-19. No USA (per requirement)._

## 1. Current state (existing 9 countries)

Dataset rebuilt 2026-06-19 (`data/processed/yield_curves.duckdb`, ~3.8M rows). Coverage:

| Cn | History start | Latest | Tenors | 1M–30Y | Notes |
|----|---------------|--------|--------|--------|-------|
| GB | 1979 | current | dense, 1M–38Y (130) | ✅ full | BoE official curve, best |
| JP | 1974 | current | 1Y–40Y (15) | ⚠️ no <1Y | MoF CSV; needs T-bill for short end |
| SE | 1990 | current | 1M–50Y (15) | ✅ | Riksbank API |
| DE | 1997 | current | 1Y–30Y (10) | ⚠️ no <1Y | Bundesbank API; needs MM/Bubill short end |
| NL | 2002 | 2026-05 | 1M–31Y (44) | ✅ | **FIXED 2026-06-19** (dynamic ODS link) |
| IT | 1988 | current | 3/5/10/30Y (4) | ⚠️ sparse | BDS/Borsa; only 4 tenors |
| AU | 2017 | current | 1M–50Y (15) | ✅ | RBA F17; short history |
| NO | 2019 | current | 1M–50Y (15) | ✅ | Norges Bank SDMX; short history |
| SG | ~6 days | current | 1M–50Y (15) | ❌ | MAS page = rolling window only |

## 2. Remaining fixes for existing countries

- **JP/DE short end (<1Y)** — official constant-maturity curves start at 1Y. Add a second
  money-market source per country: JP = MoF Treasury Discount Bills; DE = Bundesbank Bubills /
  EURIBOR-area MM series (BBK time series). New source module + merge into curve.
- **SG long history** — MAS `BenchmarkPricesAndYields.aspx` exposes only ~6 days. Investigate the
  MAS statistics "FDANET" historical query endpoint (POST with date range) for full history.
- **IT thin curve** — only 3/5/10/30Y. Banca d'Italia BDS has more benchmark tenors; widen the
  BDS series selection (catalog already ingested in `data/bds/`).

## 3. Expansion — vetted stable sources (no USA)

Priority order = source stability/ease.

### Tier A — G10, clean official APIs
- **Canada (CA)** — ✅ **DONE 2026-06-19.** Bank of Canada **Valet API**, series `BD.CDN.*.DQ.YLD`
  → 2/3/5/7/10/30Y, 2001→now, 38k rows. Module `sources/canada_bankofcanada.py`. Short end
  (T-bills, separate Valet group) still TODO for sub-2Y.
- **Switzerland (CH)** — SNB data portal `data.snb.ch` cube `rendoblim` (spot yields of
  Confederation bonds, 1–30Y+), CSV/REST. Daily.
- **New Zealand (NZ)** — ⚠️ **BLOCKED.** RBNZ B2 XLSX (`/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily-close.xlsx`)
  returns HTTP 403 (WAF/bot challenge) even with browser headers. Needs a headless browser or
  authenticated scraper. Tenors only 1/2/5/10Y. Low priority — revisit with Playwright/Firecrawl.

### Tier B — Euro area members (user already has ECB area curve)
- **France (FR)** — Banque de France **Webstat** REST API; OAT / TEC yields.
  ⚠️ **Needs free API key** (register at webstat.banque-france.fr). Blocked until key provided.
- **Belgium (BE)** — **NBB.Stat** SDMX, dataset `IROLOBE2` (OLO secondary-market yields, 1–30Y daily).
  ⚠️ **Host blocks this environment** ("Connection reset by peer" on `stat.nbb.be`). Needs a
  different egress / browser / proxy.
- **Spain (ES)** — Banco de España **BE statistics** / Tesoro. Daily availability weaker; scrape.

> **ACCESS NOTE (probed 2026-06-19):** CA + CH were the last clean open-API sources. Every Tier-B/C
> target below needs provisioning — an API key, a headless browser (WAF/JS), or a dev account.
> They are NOT 15-minute clean-JSON jobs. Decide a provisioning path before continuing.

### Tier C — Major EM (heavier; access requirement probed 2026-06-19)
- **India (IN)** — **FBIL** official G-sec par yield curve, **1M–30Y daily** — best EM fit.
  ⚠️ JS portal, no direct file URL found → needs **headless browser/Firecrawl**.
- **Korea (KR)** — Bank of Korea **ECOS API** (`ecos.bok.or.kr`); KTB 1/3/5/10/20/30Y.
  ⚠️ **Needs free API key**. Host reachable.
- **Brazil (BR)** — **ANBIMA** ETTJ curve (1–30Y). ⚠️ Needs **ANBIMA developer account**.
  BCB SGS API is open + reachable but lacks a clean constant-maturity curve.
- **China (CN)** — **ChinaBond**. ⚠️ Scrape + anti-bot.
- **South Africa (ZA)** — **SARB WebIndicators** API (`custom.resbank.co.za`) — reachable (200),
  but series-list endpoint 404s; need exact govt-bond-yield series codes from SARB docs.

## 4. Per-country implementation checklist (repeat for each new source)

1. Research source: URL, format, tenors, history depth, update cadence, auth.
2. Add entry to `config/sources.yaml`.
3. New module `src/yieldcurves/sources/<country>.py` exposing `fetch_all()` (+ `fetch_all(from_date=...)`
   for incremental), following an existing module (e.g. `norway_norgesbank.py` for SDMX,
   `australia_rba.py` for CSV).
4. Add country to `_SOURCES` / `_COUNTRY_NAMES` in `cli.py`.
5. Unit tests in `src/yieldcurves/tests/test_<country>.py` (pure parse functions, mocked fetch).
6. `yieldcurves backfill -c <CC>`; verify range + tenors in duckdb.
7. Confirm `sync` (incremental) works; it auto-joins the daily launchd run.

## 4b. Storage stability — ✅ DONE 2026-06-19
- Added `YIELDCURVES_DATA_DIR` override in `storage._base_dir()`.
- Relocated the data store to `~/yield_curves_store` (off the iCloud/Desktop volume that caused
  intermittent `Operation timed out` + `...history 2.parquet` conflict copies + the original loss).
- `scripts/run_sync.sh` now exports `YIELDCURVES_DATA_DIR` → the daily launchd job writes to the
  stable store. Verified: duckdb rebuilt (11 countries / 3.84M rows), DE sync RC=0, no timeouts.
- Old in-repo `data/` on Desktop left as a backup; interactive CLI without the env var still uses it.
- **Still TODO (optimization):** partition the history parquet (by country/year) so updates don't
  rewrite the full 184MB monolith every time. Mitigated for now by the off-Desktop relocation +
  single-writer discipline. NOTE: concurrent heavy python runs cause `SIGBUS` (mmap under memory
  pressure) — run pipeline single-process.

## 5. Known tech debt
- `yield_curves_latest.parquet` == full history (not deduped to most-recent obs date); `yield_curves`
  view is therefore heavy. Fix latest-snapshot logic.
- `fetch_all()` in several sources swallows exceptions (`except: pass`) — hides provider failures.
  Add logging / surface to ingestion_log.
- `import yieldcurves.cli` can segfault under memory pressure (scipy/numpy ABI). Daily single runs OK;
  avoid parallel heavy backfills.
- Daily updates: local launchd `com.romanomasiello.yieldcurves.sync` @ 19:30 → `scripts/run_sync.sh`
  → `python -m yieldcurves.cli sync --all`. Verify it survives reboots; consider GitHub Actions for HA.
