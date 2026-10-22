"""No-provider browser boundary: real cron routes and persistence, synthetic catalogs."""
from fastapi import FastAPI

import spark_cli.config
import spark_cli.models
import spark_cli.runtime_provider
from spark_cli.cron_routes import register_cron_routes

app = FastAPI()
register_cron_routes(app)

# Override only the external provider resolution boundary, never job storage.
spark_cli.config.load_config = lambda: {"providers": {"fixture": {"name": "Fixture provider"}}}
spark_cli.models.list_available_providers = lambda: []
spark_cli.runtime_provider.resolve_runtime_provider = lambda requested=None: {
    "provider": requested or "fixture", "api_key": "fixture",
}


@app.get("/api/model/info")
def info():
    return {"provider": "fixture"}


@app.get("/api/model/available")
def models(provider: str = ""):
    return {"provider": provider, "models": ["fixture-one", "fixture-two"], "warning": "", "live": False}


@app.get("/api/skills")
def skills():
    return [{"name": name, "enabled": True, "skill_id": f"opaque-{name}"} for name in ["alpha", "beta"]]
