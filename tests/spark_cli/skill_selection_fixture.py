"""Real Skills/Chat HTTP routes with a deterministic provider boundary for SP22."""
from types import SimpleNamespace

from core.spark_constants import get_spark_home
from core.spark_state import SessionDB
from spark_cli import web_server as web

app = web.app
home = get_spark_home()
captures = []

for root, marker in [(home / "skills", "PROFILE_BODY"), (home / "workspace/project/.agents/skills", "PROJECT_BODY")]:
    folder = root / "collision"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: collision\ndescription: Choose by scope\nsetup: touch {home / 'SETUP_MUST_NOT_RUN'}\n---\n{marker}")
(home / "files").mkdir(exist_ok=True)
(home / "files/fixture.txt").write_text("ATTACHMENT_BODY")
for number in range(1000):
    folder = home / "skills" / f"indexed-{number:04}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: indexed-{number:04}\ndescription: Metadata fixture\n---\n" + "Instruction body.\n" * 4096)

db = SessionDB()
for thread, source in [("alpha", "web"), ("bravo", "workspace:project")]:
    if not db.get_session(thread):
        db.create_session(thread, source)
db.close()


class FixtureAgent(SimpleNamespace):
    def run_conversation(self, message, **kwargs):
        captures.append({"thread": self.session_id, "message": message})
        return {"final_response": "Fixture answer"}


web._resolve_web_turn_route = lambda *a, **k: {"model": "fixture", "runtime": {}, "signature": "fixture"}
web._new_web_agent = lambda **kw: FixtureAgent(session_id=kw["session_id"])
web._get_web_cached_agent = lambda *args: None
web._maybe_auto_title_web = lambda *a, **k: None


@app.get("/fixture/captures")
def captured():
    return {"captures": captures, "setup_ran": (home / "SETUP_MUST_NOT_RUN").exists()}


@app.get("/fixture/baseline")
def baseline():
    from tools.skills_metadata import iter_skill_records, public_record

    return [public_record(row) for row in iter_skill_records()]


# The production SPA catch-all is already registered by web_server. Fixture
# probes must precede it; otherwise HTML masks a successful provider capture.
_fixture_routes = [route for route in app.routes if getattr(route, "path", "").startswith("/fixture/")]
app.router.routes = _fixture_routes + [route for route in app.routes if route not in _fixture_routes]
