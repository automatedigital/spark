import { expect, test, type Page, type Route } from "@playwright/test";

const sessionId = "smoke-session";
const prompt = "Summarize Spark in one sentence";
const assistantText = "Spark helps teams chat with an agent and inspect project work.";

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function mockSparkApi(page: Page) {
  await page.route("**/api/events**", async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body: "\n",
    });
  });
  await page.route("**/api/dashboard/auth/info", (route) =>
    fulfillJson(route, { require_auth_nonlocal: false, configured: false, token_file: null }),
  );
  await page.route("**/api/onboarding/status", (route) =>
    fulfillJson(route, { needs_onboarding: false, has_model: true, has_api_key: true }),
  );
  await page.route("**/api/status", (route) =>
    fulfillJson(route, { gateway_online: false, platform_status: {}, running_tasks: 0 }),
  );
  await page.route("**/api/model/status", (route) =>
    fulfillJson(route, { model: "gpt-5.5", provider: "openai", configured: true }),
  );
  await page.route("**/api/model/codex-usage", (route) =>
    fulfillJson(route, { available: false, reason: "smoke" }),
  );
  await page.route("**/api/cron/jobs", (route) => fulfillJson(route, []));
  await page.route("**/api/gateway/status", (route) =>
    fulfillJson(route, { running: false, platforms: [] }),
  );
  await page.route("**/api/workspace/projects", (route) => fulfillJson(route, { projects: [] }));
  await page.route("**/api/sessions?**", (route) =>
    fulfillJson(route, { sessions: [], total: 0, limit: 500, offset: 0 }),
  );
  await page.route("**/api/conversations", async (route) => {
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON() as { message?: string };
    expect(body.message).toBe(prompt);
    await fulfillJson(route, { ok: true, session_id: sessionId });
  });
  await page.route(`**/api/sessions/${sessionId}/forks`, (route) =>
    fulfillJson(route, { forks: [], fork_count: 0, parent_session_id: null, parent_title: null }),
  );
  await page.route(`**/api/sessions/${sessionId}/warm`, (route) =>
    fulfillJson(route, { ok: true, warm: true }),
  );
  await page.route(`**/api/sessions/${sessionId}/messages?**`, (route) =>
    fulfillJson(route, { session_id: sessionId, messages: [], has_earlier: false }),
  );
  await page.route(`**/api/conversations/${sessionId}/stream-snapshot`, (route) =>
    fulfillJson(route, {
      session_id: sessionId,
      resolved_session_id: sessionId,
      latest_session_id: sessionId,
      active_turn_session_id: sessionId,
      turn_active: true,
      stream_text: assistantText,
      stream_revision: 1,
      stream_text_chars: assistantText.length,
    }),
  );
}

test("core Chat loop accepts a prompt and renders streamed assistant text", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("spark-active-page", "chat");
    localStorage.setItem("spark-onboarding-complete", "true");
  });
  await mockSparkApi(page);

  await page.goto("/");
  await page.getByPlaceholder("Start with a goal").fill(prompt);
  await page.keyboard.press("Enter");

  await expect(page.getByText(assistantText)).toBeVisible();
});
