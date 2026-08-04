import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const fixturePath = fileURLToPath(new URL("./chat-thread-states-v1.json", import.meta.url));
const fixtureText = readFileSync(fixturePath, "utf8");
const fixture = JSON.parse(fixtureText);

const requiredScenarioIds = [
  "empty",
  "short",
  "long",
  "streaming",
  "interrupted",
  "reconnecting",
  "tool-heavy",
  "reasoning-heavy",
  "approval-pending",
  "changed-file",
  "parallel-subagents",
];

function allStrings(value) {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(allStrings);
  if (value && typeof value === "object") return Object.values(value).flatMap(allStrings);
  return [];
}

test("chat thread fixture catalog is deterministic and network-free", () => {
  assert.equal(fixture.version, "1.0.0");
  assert.equal(fixture.network.allowed, false);
  assert.equal(fixture.network.private_data, false);
  assert.deepEqual(
    fixture.scenarios.map((scenario) => scenario.id),
    requiredScenarioIds,
  );

  const fixtureIds = new Set();
  for (const scenario of fixture.scenarios) {
    assert.ok(scenario.session.id, `${scenario.id} needs a session id`);
    assert.ok(Array.isArray(scenario.messages), `${scenario.id} needs messages`);
    assert.ok(Array.isArray(scenario.events), `${scenario.id} needs events`);
    assert.ok(!fixtureIds.has(scenario.session.id), `duplicate session id: ${scenario.session.id}`);
    fixtureIds.add(scenario.session.id);
  }
});

test("chat thread fixtures contain no private data or network dependencies", () => {
  const strings = allStrings(fixture);
  const forbidden = [
    /https?:\/\//i,
    /\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b/i,
    /\b(?:sk|ghp|github_pat|xoxb|AIza)[_-]?[a-z0-9]{12,}\b/i,
    /\/Users\//,
    /\/home\//,
    /-----BEGIN [^-]+-----/,
  ];

  for (const value of strings) {
    for (const pattern of forbidden) {
      assert.doesNotMatch(value, pattern, `forbidden value in fixture: ${value}`);
    }
  }
});

test("state-specific fixture data is present", () => {
  const byId = new Map(fixture.scenarios.map((scenario) => [scenario.id, scenario]));

  assert.equal(byId.get("empty").messages.length, 0);
  assert.equal(byId.get("streaming").messages.at(-1).streaming, true);
  assert.equal(byId.get("interrupted").expected.retry_visible, true);
  assert.equal(byId.get("reconnecting").transport.recovery_action, "resume_from_sequence");
  assert.equal(byId.get("tool-heavy").messages.filter((message) => message.role === "tool").length, 3);
  assert.equal(byId.get("reasoning-heavy").messages.filter((message) => message.role === "reasoning").length, 1);
  assert.equal(byId.get("approval-pending").messages.at(-1).resolved, false);
  assert.equal(byId.get("changed-file").changed_files.length, 2);
  assert.equal(byId.get("parallel-subagents").subagents.length, 2);
});
