// Provider-free mounted fixture for the production Markdown renderer.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Markdown } from "../src/components/Markdown";
import "../src/index.css";

const sample = ["NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"].map((kind) =>
  `> [!${kind}]\n> **Read** this callout.\n> Second line with [Help](#help).\n>\n> - First step\n> - Second step`,
).join("\n\n") + "\n\n> Ordinary quote\n\n> [!UNKNOWN]\n> Keep this quote.\n\n```md\n> [!WARNING]\n> Literal code\n```";

export function Fixture() {
  const [content, setContent] = useState(sample);
  const [streaming, setStreaming] = useState(false);
  const [safeMode, setSafeMode] = useState(false);
  return <main className="bg-background text-foreground p-6 space-y-4 min-h-screen">
    <h1>Markdown callouts</h1>
    <label>Theme <select aria-label="Theme" onChange={(e) => { document.documentElement.dataset.webuiTheme = e.target.value; }}>
      {["codex", "spark", "daylight", "signal", "aurora", "ember", "orchid", "harbor"].map((theme) => <option key={theme}>{theme}</option>)}
    </select></label>
    <label className="block">Markdown source<textarea aria-label="Markdown source" className="block w-full h-24 border" value={content} onChange={(e) => setContent(e.target.value)} /></label>
    <label><input type="checkbox" checked={streaming} onChange={(e) => setStreaming(e.target.checked)} /> Streaming</label>
    <label><input type="checkbox" checked={safeMode} onChange={(e) => setSafeMode(e.target.checked)} /> Safe mode</label>
    <section aria-label="Rendered response"><Markdown content={content} streaming={streaming} safeMode={safeMode} showStreamingCursor={streaming} /></section>
    <button id="help" type="button">Help destination</button>
  </main>;
}

createRoot(document.getElementById("root")!).render(<Fixture />);
