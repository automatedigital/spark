from spark_cli import web_turn_state


class FakeClock:
    def __init__(self, *values: float):
        self._values = list(values)

    def __call__(self) -> float:
        if self._values:
            return self._values.pop(0)
        return 999.0


class FakeSessionDB:
    def __init__(
        self,
        *,
        resolved: dict[str, str | None] | None = None,
        latest: dict[str, str | None] | None = None,
    ):
        self.resolved = resolved or {}
        self.latest = latest or {}
        self.closed = False

    def resolve_session_id(self, session_id: str) -> str | None:
        return self.resolved.get(session_id)

    def resolve_latest_descendant(self, session_id: str) -> str | None:
        return self.latest.get(session_id)

    def close(self) -> None:
        self.closed = True


def test_active_turn_lifecycle_updates_and_clears():
    turns: dict[str, web_turn_state.WebActiveTurn] = {}
    db = FakeSessionDB()
    clock = FakeClock(100.0, 101.0, 102.0)

    turn = web_turn_state.mark_web_turn_active(
        "s1",
        status="Starting",
        phase="starting",
        turns=turns,
        session_db_factory=lambda: db,
        clock=clock,
    )

    assert turns == {"s1": turn}
    assert turn.started_at == 100.0
    assert turn.last_event_at == 100.0
    assert web_turn_state.is_web_turn_active("s1", turns=turns, session_db_factory=lambda: db)

    web_turn_state.touch_web_turn(
        "s1",
        status="Running",
        phase="api",
        interrupt_requested=True,
        active_agent_session_id="agent-s1",
        turns=turns,
        session_db_factory=lambda: db,
        clock=clock,
    )

    assert turn.status == "Running"
    assert turn.phase == "api"
    assert turn.interrupt_requested is True
    assert turn.active_agent_session_id == "agent-s1"
    assert turn.last_event_at == 101.0

    web_turn_state.append_web_turn_token(
        "s1",
        "hello",
        turns=turns,
        session_db_factory=lambda: db,
        clock=clock,
    )

    assert turn.phase == "streaming"
    assert turn.stream_text == "hello"
    assert turn.stream_revision == 1
    assert turn.last_event_at == 102.0

    web_turn_state.clear_web_turn("s1", turns=turns, session_db_factory=lambda: db)

    assert turns == {}
    assert not web_turn_state.is_web_turn_active("s1", turns=turns, session_db_factory=lambda: db)
    assert db.closed is True


def test_alias_resolves_to_latest_descendant_turn_and_agent():
    turns: dict[str, web_turn_state.WebActiveTurn] = {}
    db = FakeSessionDB(
        resolved={"alias": "parent"},
        latest={"parent": "child", "child": "child"},
    )

    web_turn_state.mark_web_turn_active(
        "child",
        status="Running",
        turns=turns,
        session_db_factory=lambda: db,
        clock=FakeClock(50.0),
    )

    assert web_turn_state.resolve_web_turn_ids("alias", session_db_factory=lambda: db) == {
        "requested": "alias",
        "resolved": "parent",
        "latest": "child",
    }
    assert web_turn_state.web_turn_key("alias", session_db_factory=lambda: db) == "child"

    active_key, turn = web_turn_state.get_web_turn(
        "alias",
        turns=turns,
        session_db_factory=lambda: db,
    )
    assert active_key == "child"
    assert turn is turns["child"]

    agent = object()
    agent_key, found_agent = web_turn_state.get_web_agent_for_turn(
        "alias",
        {"child": agent},
        turns=turns,
        session_db_factory=lambda: db,
    )
    assert agent_key == "child"
    assert found_agent is agent


def test_agent_lookup_falls_back_to_active_agent_session_id():
    turns: dict[str, web_turn_state.WebActiveTurn] = {}
    db = FakeSessionDB()
    agent = object()

    web_turn_state.mark_web_turn_active(
        "visible-session",
        active_agent_session_id="compressed-session",
        turns=turns,
        session_db_factory=lambda: db,
        clock=FakeClock(10.0),
    )

    agent_key, found_agent = web_turn_state.get_web_agent_for_turn(
        "visible-session",
        {"compressed-session": agent},
        turns=turns,
        session_db_factory=lambda: db,
    )

    assert agent_key == "compressed-session"
    assert found_agent is agent


def test_migrate_web_turn_moves_state_to_new_session_id():
    turns = {
        "old": web_turn_state.WebActiveTurn(
            started_at=1.0,
            last_event_at=1.0,
            status="Running",
            interrupt_requested=False,
            active_agent_session_id="old",
            phase="streaming",
        )
    }
    db = FakeSessionDB()

    old_key, turn = web_turn_state.migrate_web_turn(
        "old",
        "new",
        status="Context compressed; continuing",
        active_agent_session_id="new",
        turns=turns,
        session_db_factory=lambda: db,
        clock=FakeClock(2.0),
    )

    assert old_key == "old"
    assert "old" not in turns
    assert turns["new"] is turn
    assert turn is not None
    assert turn.status == "Context compressed; continuing"
    assert turn.active_agent_session_id == "new"
    assert turn.last_event_at == 2.0
