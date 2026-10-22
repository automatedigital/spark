/** Deliberately bounded, passive chat diagrams. Config and actions stay app-owned. */
export const MERMAID_MAX_CHARS = 8_000;
export const MERMAID_MAX_LINES = 150;

export function mermaidSourceError(source: string): string | null {
  if (source.length > MERMAID_MAX_CHARS || source.split("\n").length > MERMAID_MAX_LINES) {
    return "Diagram exceeds the size limit (8,000 characters or 150 lines).";
  }
  if (!source.trim()) return "Diagram source is empty.";
  // No frontmatter/config directives, HTML/entities, links, CSS or external assets.
  // Strict mode is also enforced by Mermaid, followed by SVG-only sanitization.
  if (/%%\{|^\s*---|<\s*[a-z/!?]|&|\b(?:click|style|classDef|linkStyle)\s|\b(?:href|https?|javascript|data|image|icon)\s*[:(]|@\{/im.test(source)) {
    return "Diagram contains unsupported HTML, links, styling or configuration.";
  }
  return null;
}
