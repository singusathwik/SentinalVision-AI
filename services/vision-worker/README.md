# Worker entry point

From repository root set `PYTHONPATH=services/api` and run `python -m sentinel.worker`.
The shared implementation lives in the `sentinel` package so domain rules and persistence are not duplicated. For Linux Redis operation: `celery -A sentinel.tasks:celery worker --concurrency=1` with `SENTINEL_QUEUE=celery`. Windows native profile uses the database queue; native Celery is not the tested profile.
