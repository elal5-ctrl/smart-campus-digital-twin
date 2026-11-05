# Changelog — weather\_adjusted\_traffic.py

## New dependency

```
pip install psycopg2-binary
```

---

## Configuration block (top of file)

Six new constants were added near the top of the script. Fill these in before running:

```python
DB_HOST     = "localhost"
DB_PORT     = 5432
DB_NAME     = "your\_db\_name"
DB_USER     = "your\_db\_user"
DB_PASSWORD = "your\_password"
DB_TABLE    = "weather\_traffic\_predictions"
```

---

## PostgreSQL output

Every run now writes predictions to the database table defined by `DB\_TABLE` in addition to the CSV. The table is created automatically on first run if it does not exist.

Rows are upserted on `(node\_id, timestamp)`, so re-running the script for an overlapping time window is safe — no duplicates.

Use `--no-db` to skip the database write and produce a CSV only (useful for testing without a live DB connection).

---

## Continuous mode (`--continuous`)

The script can now run indefinitely instead of exiting after one batch.

```bash
python weather\_adjusted\_traffic.py -f weights.npz --continuous -S 2026-05-15 -o out.csv
```

* `-S` sets a fixed start timestamp. The window end advances to the current 15-minute boundary on every cycle.
* After each batch the process sleeps until the next clock boundary (`:00`, `:15`, `:30`, `:45`) and then runs again.
* `-E`/`--end` is not used in continuous mode and can be omitted entirely.

In one-shot mode (no `--continuous`) the behaviour is identical to before: both `-S` and `-E` are required and the script exits after writing one batch.


