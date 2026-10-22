"""No-provider browser boundary: real cron routes and persistence, real skill files and synthetic provider catalogs."""
from fastapi import FastAPI

import spark_cli.config
import spark_cli.models
import spark_cli.runtime_provider
from core.spark_constants import get_spark_home
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


# Real files intentionally have duplicate labels and different execution paths.

for folder, instruction in (("alpha-folder", "ALPHA_INSTRUCTION"), ("group/beta-folder", "BETA_INSTRUCTION")):
    directory = get_spark_home() / "skills" / folder
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"---\nname: FriendlySkill\ndescription: fixture\n---\n{instruction}\n")


@app.get("/fixture/prompt/{job_id}")
def job_prompt(job_id: str):
    from cron.jobs import get_job
    from cron.scheduler import _build_job_prompt

    return {"prompt": _build_job_prompt(get_job(job_id))}
