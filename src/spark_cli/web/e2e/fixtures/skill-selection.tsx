import { useState } from "react";
import { createRoot } from "react-dom/client";
import SkillsToolsPage from "../../src/components/settings/SkillsToolsPage";
import { ContextTray } from "../../src/components/chat/ContextTray";
import { PromptBar } from "../../src/components/chat/PromptBar";
import { useChatDraft } from "../../src/hooks/useChatDraft";
import { fetchJSON } from "../../src/lib/apiHelpers";
import { I18nProvider } from "../../src/i18n";
import "../../src/index.css";

export default function Fixture() {
  const [thread, setThread] = useState("alpha");
  const [view, setView] = useState("chat");
  const draft = useChatDraft(thread === "bravo" ? "project" : null, thread);
  const [result, setResult] = useState("");
  const submit = async () => {
    const acknowledge = draft.capture();
    try {
      const accepted = await fetchJSON<{ turn_id: string }>(`/api/conversations/${thread}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: draft.input, context_items: draft.contextItems, submission_id: crypto.randomUUID() }),
      });
      acknowledge();
      setResult(`Accepted ${accepted.turn_id}`);
    } catch (error) { setResult(String(error)); }
  };
  return <div className="flex h-screen flex-col">
    <nav>{["alpha", "bravo"].map((id) => <button key={id} onClick={() => { setThread(id); setView("chat"); }}>{id}</button>)}<button onClick={() => setView("skills")}>Browse skills</button></nav>
    {view === "skills" ? <SkillsToolsPage /> : <>
      <p>Thread {thread}</p>
      <button onClick={() => draft.setContextItems((items) => [...items, { id: "attachment", type: "file", source_path: "files/fixture.txt", scope: "one_turn", inclusion_mode: "full", size_bytes: 15, label: "fixture.txt", attachment_status: "ready" }])}>Add fixture attachment</button>
      <ContextTray items={draft.contextItems} onRemove={(id) => draft.setContextItems((items) => items.filter((item) => item.id !== id))} onUpdateMode={() => {}} onUpdateScope={() => {}} />
      <PromptBar input={draft.input} setInput={draft.setInput} streaming={false} disabled={!draft.ready} onSend={() => void submit()} onStop={() => {}} draftScopeKey={draft.scopeKey} sessionId={thread} workspaceSlug={thread === "bravo" ? "project" : undefined} contextItems={draft.contextItems} onRemoveContextItem={(id) => draft.setContextItems((items) => items.filter((item) => item.id !== id))} />
      <output>{result}</output>
    </>}
  </div>;
}
createRoot(document.getElementById("root")!).render(<I18nProvider><Fixture /></I18nProvider>);
