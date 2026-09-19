# ITCS355 Capstone — PM2.5 six-hour nowcast

Predicts PM2.5 for the next six hours at each of 39 monitoring stations in Thailand, as a
scheduled hourly batch job. Built for whoever decides whether an outdoor activity goes
ahead: a school, a parent, a site supervisor.

**Status:** step 1 complete. Six months of history downloaded and versioned.

## Data

| | |
|---|---|
| Source | OpenAQ v3 API |
| Provider | AirGradient (40 stations pinned, 39 reporting) |
| Licence | **CC BY 4.0** — attribution to AirGradient and to OpenAQ |
| Window | 2026-03-23 to 2026-09-19 |
| Rows | 155,109 hourly readings |
| Coverage | 92.1% of every possible station-hour |

The station list is pinned in [`data/stations.json`](data/stations.json), with each
station's provider and licence recorded beside it. "All Thai stations" is a different set
every month; a pinned list is what makes the dataset rebuildable.

Stations whose licence OpenAQ does not state are **excluded by default** —
`scripts/find_stations.py` requires an explicit flag to include them. That drops the 263
government Air4Thai monitors, which are the more authoritative source but carry no stated
licence. An unstated licence is not a permissive one.

## Reproduce the dataset

```bash
cp .env.example .env          # then paste your free OpenAQ key into it
pip install -r requirements.txt
python scripts/find_stations.py --country TH --limit 40
python scripts/download_measurements.py --months 6
```

Or, to get the exact data this project was built on rather than today's:

```bash
dvc pull
```

## What the data already shows

Monthly median PM2.5, across all stations:

| Month | µg/m³ |
|---|--:|
| March | 76.1 |
| April | 72.0 |
| May | 12.5 |
| June | 5.6 |
| July | 7.7 |
| August | 5.6 |
| September | 9.8 |

Burning season is in the data, unprompted. March sits 13x above June. This is the
distribution shift the monitoring half of the project detects — a real one, not an
injected one.

18.3% of all readings exceed Thailand's 24-hour standard of 37.5 µg/m³.

## Credentials

The OpenAQ key lives in `.env`, which is gitignored. A committed key is an automatic
deduction under the capstone brief, so no script accepts the key as a command line
argument either — an argument is visible in shell history and in the process list.

## Attribution

Air quality data from [AirGradient](https://www.airgradient.com/), obtained via
[OpenAQ](https://openaq.org/), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
