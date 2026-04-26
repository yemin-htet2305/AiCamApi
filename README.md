# AiCamApi

The middle layer of AiCam. A Flask app that reads the lab's daily entry counts from MongoDB and serves them over HTTP as JSON. The dashboard is the only thing that calls it today, but it's a plain REST API — you can hit it with `curl`, Postman, a notebook, or any other client.

**Author:** Ye Min Htet
**Stack:** Python 3, Flask, Flask-CORS, pymongo
**Runs on:** `<raspberrypi.address>:5001`, managed by pm2

For the big picture, see the [root README](../README.md). For the full endpoint spec, see [`API_REFERENCE.md`](../API_REFERENCE.md).

---

## What this does

The Pi writes daily entry totals into MongoDB. The dashboard needs to ask questions like "what was the peak day?" or "what's the 30-day trend?" This API is the thing that translates those questions into Mongo queries and returns JSON.

### Endpoints at a glance

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/seed` | Insert one day's record |
| `POST` | `/api/seed/bulk` | Insert many records at once |
| `GET` | `/api/history` | Filtered, sorted list of daily records |
| `GET` | `/api/stats/summary` | Totals, averages, min, max |
| `GET` | `/api/stats/daily-avg` | Average entries per day (optionally per month) |
| `GET` | `/api/stats/peak` | Top N busiest days |
| `GET` | `/api/stats/trend` | Direction + % change over the last N days |

Full request/response details are in [`API_REFERENCE.md`](../API_REFERENCE.md).

---

## ⚠️ Before you run — check the MongoDB host

Open `labEntriesApi.py` and find:

```python
client = MongoClient("mongodb://localhost:27017/")
```

In our lab, **MongoDB runs on another raspberrypi server**, not on the API server. That line needs to become:

```python
client = MongoClient("mongodb://<another_raspberrypi_server.address>:27017/")
```

The committed code ships with `localhost` as a default for local testing. **You have to change it after cloning** or the API will start up fine and then throw `ServerSelectionTimeoutError` on the first request.

If you're running a self-contained test setup (API and MongoDB on the same machine), `localhost` is fine — but in our lab's production deployment, it isn't.

---

## Installation

The API needs Python 3 and three packages. Nothing more.

### 1. Python packages

```bash
pip install flask flask-cors pymongo
```

If you're on a Debian/Ubuntu system with PEP 668 externally-managed Python (Bookworm, 24.04, etc.), add `--break-system-packages` or use a virtualenv:

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask flask-cors pymongo
```

### 2. MongoDB

MongoDB runs in Docker on the DB server (`192.168.1.104`). This avoids the system-package install and makes it easy to upgrade or reset the DB without touching the host OS.

If MongoDB isn't already running, start it like this:

```bash
docker run -d \
  --name aicam-mongo \
  --restart unless-stopped \
  -p 27017:27017 \
  -v aicam-mongo-data:/data/db \
  mongo:latest
```

What each flag does:

- `-d` — run in the background (detached).
- `--name aicam-mongo` — names the container so you can refer to it later (`docker logs aicam-mongo`, `docker restart aicam-mongo`).
- `--restart unless-stopped` — Docker brings the container back automatically after a reboot or crash, unless you've explicitly stopped it.
- `-p 27017:27017` — maps the host's port `27017` to the container's port `27017`, so the API and the Pi can reach Mongo over the LAN.
- `-v aicam-mongo-data:/data/db` — stores the database files in a Docker volume named `aicam-mongo-data`. **This is what keeps your data alive across container restarts and image upgrades.** Without it, removing the container deletes every record.

Verify it's running:

```bash
docker ps                    # should show aicam-mongo as Up
docker logs aicam-mongo      # confirm it's accepting connections
```

To connect from the host for a quick check:

```bash
docker exec -it aicam-mongo mongosh
> use aicam_db
> db.daily_counts.findOne()
```

**About network access:** because the container publishes port `27017` with `-p 27017:27017`, MongoDB is reachable from any machine on the LAN that can reach `192.168.1.104:27017` — which is exactly what we want, since the Pi (on a different machine) needs to write to it.

**About security:** the Mongo container runs without authentication. This is fine on a closed lab LAN with no internet exposure. It is **not** fine if this machine is ever reachable from outside. If the deployment ever changes, turn on authentication — there's a note about this in [`EXTENDING.md`](../EXTENDING.md).

**Useful commands:**

```bash
docker stop aicam-mongo          # stop without removing
docker start aicam-mongo         # start it again
docker restart aicam-mongo       # both
docker logs -f aicam-mongo       # tail logs
docker rm -f aicam-mongo         # remove the container (data survives in the volume)
docker volume ls                 # confirm the aicam-mongo-data volume exists
```

### 3. The collection

No schema migration, no seed script. The first time the Pi (or a `POST /api/seed` call) writes a record, MongoDB creates the `aicam_db` database and `daily_counts` collection automatically.

To verify:

```bash
mongosh
> use aicam_db
> db.daily_counts.findOne()
```

If that returns a document, you're connected. If it returns `null`, the collection exists but is empty, which is also fine.

---

## Running it manually (first-time test)

Before pm2, confirm it works standalone:

```bash
cd AiCamApi
python3 labEntriesApi.py
```

You should see:

```
 * Serving Flask app 'labEntriesApi'
 * Debug mode: on
 * Running on http://127.0.0.1:5001
```

In another terminal:

```bash
curl http://localhost:5001/api/stats/summary
```

If the collection is empty you'll get:

```json
{"error": "No data found"}
```

That's the right answer — the API is running, it just has nothing to show yet. Throw in a test record:

```bash
curl -X POST http://localhost:5001/api/seed \
  -H "Content-Type: application/json" \
  -d '{"date": "2025-04-24", "entries": 42}'
```

Then re-run the summary call and you should get actual numbers back.

---

## Running under pm2 (production)

```bash
pm2 start labEntriesApi.py --name aicam-api --interpreter python3
pm2 save
pm2 startup      # follow the command it prints so pm2 comes back on reboot
```

Useful commands:

```bash
pm2 logs aicam-api              # tail API logs
pm2 restart aicam-api           # after changing the code
pm2 stop aicam-api              # halt without removing
pm2 delete aicam-api            # remove from pm2
pm2 monit                       # live CPU / memory view
```

**A note about debug mode:** the script ends with `app.run(debug=True, port=5001, use_reloader=False)`. Debug mode is on, which is convenient for development but exposes stack traces on errors and is explicitly not recommended for production by Flask itself. In our lab it's acceptable because the API is only reachable from the LAN, but if you ever deploy more widely, change that to `debug=False` — and at that point you should really be running behind Gunicorn or uWSGI, not Flask's built-in server. See [`EXTENDING.md`](../EXTENDING.md) for notes on upgrading to a real WSGI server.

---

## How the endpoints work (high level)

### `POST /api/seed` and `POST /api/seed/bulk`

These were built for seeding and testing. The Pi does **not** go through these endpoints — it writes to MongoDB directly using pymongo. The seed endpoints exist so you can:

- Insert historical data by hand (e.g. back-fill a week of test data for the dashboard).
- Run demo/evaluation setups without needing a real Pi.

### `GET /api/history`

The list endpoint. Supports query params:

- `date=YYYY-MM-DD` — single day
- `from=YYYY-MM-DD&to=YYYY-MM-DD` — range (either bound optional)
- `min_entries=N&max_entries=N` — filter by entry count (either bound optional)
- `sort=asc|desc` — defaults to `desc`

All filters combine with AND logic. See [`API_REFERENCE.md`](../API_REFERENCE.md#gethistory) for exact examples.

### `GET /api/stats/summary`

Loops over every document in the collection and returns total days, total entries, average, min, max. Fast enough for now — the collection is one document per day, so even five years of data is under 2000 documents. If this ever gets slow, cache it or precompute with an aggregation pipeline.

### `GET /api/stats/daily-avg`

Returns the average `entry_count` across all documents, optionally filtered by month. The month filter uses a MongoDB regex match (`{"date": {"$regex": f"^{month}"}}`) because `date` is stored as a string like `2025-04-24`. Crude but works.

### `GET /api/stats/peak`

Sorts by `entry_count` descending and returns the top `n` (default 1, clamp yourself if you pass a huge number).

### `GET /api/stats/trend`

Grabs the last `N` days (default 7), splits them in half chronologically, compares the average of the first half to the average of the second half, and returns:

- `direction` — `"up"`, `"down"`, or `"flat"`
- `change_pct` — percentage change rounded to one decimal
- `data` — the raw daily values for the chart

Needs at least 2 data points or it returns a 400.

---

## Configuration

No `.env` file, no config module. Everything is hardcoded:

| What | Where | Default |
|---|---|---|
| MongoDB URI | `labEntriesApi.py` line ~9 | `mongodb://localhost:27017/` |
| Database name | same file | `aicam_db` |
| Collection name | same file | `daily_counts` |
| Port | end of file | `5001` |
| Debug mode | end of file | `True` |
| CORS | `CORS(app)` | allow all origins |

Moving any of these to environment variables is a good first extension — see [`EXTENDING.md`](../EXTENDING.md).

---

## CORS

The API calls `CORS(app)` with no arguments, which means **every origin is allowed**. The dashboard, a Jupyter notebook on a different machine, a random browser tab on somebody's phone — all of it can hit the API.

This is fine for a lab-internal API on a closed network. If the API ever becomes reachable from outside the lab, lock this down:

```python
CORS(app, origins=["http://192.168.1.126:3000"])
```

---

## Troubleshooting

**`pymongo.errors.ServerSelectionTimeoutError` on any request**
The API can't reach MongoDB. In order:
1. Is the MongoDB URI correct? (Most common cause — you didn't change `localhost` after cloning.)
2. Is the Mongo container actually running? `docker ps` on the DB server should show `aicam-mongo` as `Up`. If it's not, `docker start aicam-mongo`. If the container doesn't exist at all, see the MongoDB section above for the initial `docker run` command.
3. Is the container exposing port `27017` to the host? `docker port aicam-mongo` should show `27017/tcp -> 0.0.0.0:27017`.
4. Is there a firewall between the API server and the DB server?

**API starts, endpoints return 404 for everything**
You're hitting the wrong port or the wrong path prefix. All endpoints begin with `/api/` — a bare `curl http://localhost:5001/` returns 404 by design.

**Dashboard can't reach the API**
1. Check `AiCamDashboard/lib/api.ts` — the `API_BASE_URL` constant. Default is `http://localhost:5001/api` which only works if the dashboard and API are on the same machine.
2. If they're on the same machine but it still doesn't work, check the browser console — CORS errors look like CORS errors.
3. If they're on different machines, set the URL to the API server's real IP.

**`{"error": "No data found"}`**
Expected when the collection is empty. Either wait for the Pi to write a real record (first one at 18:00), or seed test data via `POST /api/seed`.

**`KeyError: 'entries'` on `POST /api/seed`**
You sent `entry_count` instead of `entries`. The seed endpoint expects `{"date": "...", "entries": N}`, not the field name used in the DB. Yes, it's inconsistent. It's one of the crude bits — see [`EXTENDING.md`](../EXTENDING.md).

---

## Known quirks

Repeating from the root README for visibility here:

- **`saved_at` format inconsistency.** The Pi writes `saved_at` as a Python `datetime` object (BSON date). The API's `/api/seed` endpoints write it as a formatted string (`"2025-04-24 18:00:00"`). Both work for display, but if you ever query on `saved_at`, the types won't match.
- **Field name mismatch.** The API reads `entry_count` from Mongo but accepts `entries` in the seed POST body, and returns `entries` in JSON responses. Three names for the same thing.
- **No validation.** The seed endpoints don't check that `date` is a real date string or that `entries` is a non-negative integer. Garbage in, garbage through to Mongo.
- **`debug=True` in production.** See the pm2 section above.

---

## What's worth improving

1. **Environment-variable config** for the Mongo URI, port, and debug flag. One `.env` file, a few `os.getenv()` calls.
2. **Gunicorn instead of Flask's dev server.** `pm2 start "gunicorn -w 4 -b 0.0.0.0:5001 labEntriesApi:app" --name aicam-api`.
3. **Normalize the field names.** Pick one of `entries` / `entry_count` and use it everywhere.
4. **Input validation** on the seed endpoints. Even a simple `pydantic` model or manual `isinstance` check would prevent bad data.
5. **Authentication.** Flask-Login or a simple API-key header. Only if the API ever leaves the LAN.
6. **Aggregation pipeline** for `/api/stats/summary`. One `$group` stage on the server beats loading every document into Python.

See [`EXTENDING.md`](../EXTENDING.md) for how to approach these.

---

— Ye Min Htet
