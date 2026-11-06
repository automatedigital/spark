"""SP17 browser fixture: real schedules/storage; frozen clock, synthetic provider."""
from datetime import datetime, timezone

from fastapi.middleware.cors import CORSMiddleware

import cron.jobs
import spark_cli.config
import spark_cli.runtime_provider
from cron_overrides_fixture import app

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
cron.jobs._spark_now = lambda: datetime(2026, 3, 28, 12, tzinfo=timezone.utc)
fixture_config = {
    "model": {"default": "fixture-model", "provider": "custom:fixture"},
    "providers": {"fixture": {"url": "http://127.0.0.1:1/v1", "name": "Fixture provider"}},
}
spark_cli.config.load_config = lambda: fixture_config
spark_cli.runtime_provider.load_config = lambda: fixture_config
