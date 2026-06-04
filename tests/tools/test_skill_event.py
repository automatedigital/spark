"""skill_manage emits a skills.updated event on successful writes (4.1.3)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tools.skill_manager_tool import skill_manage

VALID_SKILL_CONTENT = """\
---
name: evt-skill
description: A test skill for the event check.
---

# Evt Skill

Step 1: Do the thing.
"""


@contextmanager
def _skill_dir(tmp_path):
    with patch("tools.skill_manager_tool.SKILLS_DIR", tmp_path), \
         patch("agent.skill_utils.get_all_skills_dirs", return_value=[tmp_path]):
        yield


def test_create_emits_skills_updated(tmp_path):
    events = []
    with _skill_dir(tmp_path), \
         patch("spark_cli.web_server._publish_event", lambda topic, data: events.append((topic, data))):
        raw = skill_manage(action="create", name="evt-skill", content=VALID_SKILL_CONTENT)
    assert '"success": true' in raw
    assert ("skills.updated", {"action": "create", "name": "evt-skill"}) in events


def test_failed_write_emits_no_event(tmp_path):
    events = []
    with _skill_dir(tmp_path), \
         patch("spark_cli.web_server._publish_event", lambda topic, data: events.append((topic, data))):
        # Invalid content → failure → no event.
        skill_manage(action="create", name="bad-skill", content="no frontmatter")
    assert events == []
