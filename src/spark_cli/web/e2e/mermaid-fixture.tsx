import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Markdown } from "../src/components/Markdown";

let root: Root | undefined;
export function renderMarkdown(content: string, streaming = false, safeMode = false) {
  root ??= createRoot(document.getElementById("fixture")!);
  root.render(createElement(Markdown, { content, streaming, safeMode }));
}
export function unmountMarkdown() {
  root?.unmount();
  root = undefined;
}
