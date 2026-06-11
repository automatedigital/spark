/** Compact display name for a model id (e.g. "claude-fable-5" → "Fable 5"). */
export function shortModelName(model: string): string {
  const m = model.toLowerCase();
  if (m.includes("claude")) {
    const parts = model.replace(/^claude-/i, "").split("-");
    const name = parts[0] ? parts[0].charAt(0).toUpperCase() + parts[0].slice(1) : "";
    const version = parts.slice(1).join(".");
    return version ? `${name} ${version}` : name;
  }
  if (m.startsWith("gpt")) return model.toUpperCase();
  if (m.startsWith("gemini")) {
    const parts = model.split("-");
    const name = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
    const version = parts.slice(1, 3).join(".");
    return version ? `${name} ${version}` : name;
  }
  const first = model.split(/[-_/]/)[0];
  return first.charAt(0).toUpperCase() + first.slice(1);
}
