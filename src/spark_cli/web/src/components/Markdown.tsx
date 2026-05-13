import { useMemo, useState } from "react";
import hljs from "highlight.js/lib/core";
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import yaml from "highlight.js/lib/languages/yaml";
import sql from "highlight.js/lib/languages/sql";
import xml from "highlight.js/lib/languages/xml";
import css from "highlight.js/lib/languages/css";
import markdown from "highlight.js/lib/languages/markdown";
import rust from "highlight.js/lib/languages/rust";
import go from "highlight.js/lib/languages/go";
import { Copy, CheckCheck } from "lucide-react";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("tsx", typescript);
hljs.registerLanguage("jsx", javascript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("shell", bash);
hljs.registerLanguage("zsh", bash);
hljs.registerLanguage("json", json);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("css", css);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("md", markdown);
hljs.registerLanguage("rust", rust);
hljs.registerLanguage("rs", rust);
hljs.registerLanguage("go", go);

/**
 * Lightweight markdown renderer for LLM output.
 * Handles: fenced code (+ syntax highlight + copy), tables, task lists,
 * blockquotes, headings, hr, lists, paragraphs,
 * inline: bold, italic, strikethrough, code, links, bare URLs.
 */
export function Markdown({ content, highlightTerms }: { content: string; highlightTerms?: string[] }) {
  const blocks = useMemo(() => parseBlocks(content), [content]);

  return (
    <div className="text-sm text-foreground leading-relaxed space-y-2">
      {blocks.map((block, i) => (
        <Block key={i} block={block} highlightTerms={highlightTerms} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type BlockNode =
  | { type: "code"; lang: string; content: string }
  | { type: "heading"; level: number; content: string }
  | { type: "hr" }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "blockquote"; content: string }
  | { type: "paragraph"; content: string };

/* ------------------------------------------------------------------ */
/*  Block parser                                                       */
/* ------------------------------------------------------------------ */

function isTableSeparator(line: string): boolean {
  return /^\|[-: |]+\|?\s*$/.test(line.trim());
}

function parseTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function parseBlocks(text: string): BlockNode[] {
  const lines = text.split("\n");
  const blocks: BlockNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fenceMatch = line.match(/^```(\w*)/);
    if (fenceMatch) {
      const lang = fenceMatch[1] || "";
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", lang, content: codeLines.join("\n") });
      continue;
    }

    // Table — need header + separator + at least one row
    if (line.trim().startsWith("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const headers = parseTableRow(line);
      i += 2; // skip header and separator
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(parseTableRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,4})\s+(.+)/);
    if (headingMatch) {
      blocks.push({ type: "heading", level: headingMatch[1].length, content: headingMatch[2] });
      i++;
      continue;
    }

    // Horizontal rule
    if (/^[-*_]{3,}\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Blockquote
    if (/^>\s?/.test(line)) {
      const bqLines: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        bqLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ type: "blockquote", content: bqLines.join("\n") });
      continue;
    }

    // Unordered list (including task list items)
    if (/^[-*+]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*+]\s/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered: false, items });
      continue;
    }

    // Ordered list
    if (/^\d+[.)]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+[.)]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+[.)]\s/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered: true, items });
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph — collect consecutive non-empty, non-special lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].match(/^```/) &&
      !lines[i].match(/^#{1,4}\s/) &&
      !lines[i].match(/^[-*+]\s/) &&
      !lines[i].match(/^\d+[.)]\s/) &&
      !lines[i].match(/^[-*_]{3,}\s*$/) &&
      !lines[i].match(/^>\s?/) &&
      !lines[i].trim().startsWith("|")
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: "paragraph", content: paraLines.join("\n") });
    }
  }

  return blocks;
}

/* ------------------------------------------------------------------ */
/*  Code block with syntax highlight + copy button                    */
/* ------------------------------------------------------------------ */

function CodeBlock({ lang, content }: { lang: string; content: string }) {
  const [copied, setCopied] = useState(false);

  const highlighted = useMemo(() => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(content, { language: lang }).value;
      } catch {
        /* fall through */
      }
    }
    return null;
  }, [lang, content]);

  const handleCopy = () => {
    void navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="relative group/code rounded-md overflow-hidden border border-border/60">
      <div className="flex items-center justify-between px-3 py-1 bg-secondary/80 border-b border-border/40">
        <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
          {lang || "text"}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          title="Copy code"
        >
          {copied ? (
            <CheckCheck className="h-3 w-3 text-success" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          <span className="hidden group-hover/code:inline">{copied ? "Copied!" : "Copy"}</span>
        </button>
      </div>
      {highlighted ? (
        <pre className="bg-secondary/40 px-3 py-2.5 text-xs font-mono leading-relaxed overflow-x-auto hljs">
          <code dangerouslySetInnerHTML={{ __html: highlighted }} />
        </pre>
      ) : (
        <pre className="bg-secondary/40 px-3 py-2.5 text-xs font-mono leading-relaxed overflow-x-auto">
          <code>{content}</code>
        </pre>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Block renderer                                                     */
/* ------------------------------------------------------------------ */

function Block({ block, highlightTerms }: { block: BlockNode; highlightTerms?: string[] }) {
  switch (block.type) {
    case "code":
      return <CodeBlock lang={block.lang} content={block.content} />;

    case "heading": {
      const Tag = `h${Math.min(block.level, 4)}` as "h1" | "h2" | "h3" | "h4";
      const sizes: Record<string, string> = {
        h1: "text-base font-bold",
        h2: "text-sm font-bold",
        h3: "text-sm font-semibold",
        h4: "text-sm font-medium",
      };
      return <Tag className={sizes[Tag]}><InlineContent text={block.content} highlightTerms={highlightTerms} /></Tag>;
    }

    case "hr":
      return <hr className="border-border" />;

    case "blockquote":
      return (
        <blockquote className="border-l-2 border-primary/40 pl-3 text-muted-foreground italic bg-secondary/20 py-1 rounded-r-sm">
          <InlineContent text={block.content} highlightTerms={highlightTerms} />
        </blockquote>
      );

    case "table":
      return (
        <div className="overflow-x-auto rounded-md border border-border/60">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-secondary/60 border-b border-border/60">
                {block.headers.map((h, i) => (
                  <th key={i} className="px-3 py-2 text-left font-semibold text-foreground whitespace-nowrap">
                    <InlineContent text={h} highlightTerms={highlightTerms} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 0 ? "bg-background" : "bg-secondary/20"}>
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3 py-1.5 border-t border-border/30 text-foreground/90">
                      <InlineContent text={cell} highlightTerms={highlightTerms} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag className={`space-y-0.5 ${block.ordered ? "list-decimal" : "list-disc"} pl-5 text-sm`}>
          {block.items.map((item, i) => {
            // Task list: "[ ] ..." or "[x] ..."
            const taskMatch = item.match(/^\[([ xX])\]\s+(.*)/);
            if (taskMatch) {
              const done = taskMatch[1].toLowerCase() === "x";
              return (
                <li key={i} className="list-none -ml-5 flex items-start gap-2">
                  <span
                    className={`mt-0.5 shrink-0 h-3.5 w-3.5 rounded-sm border flex items-center justify-center text-[10px] ${
                      done
                        ? "bg-success/20 border-success/50 text-success"
                        : "border-muted-foreground/40"
                    }`}
                  >
                    {done ? "✓" : ""}
                  </span>
                  <span className={done ? "line-through text-muted-foreground" : ""}>
                    <InlineContent text={taskMatch[2]} highlightTerms={highlightTerms} />
                  </span>
                </li>
              );
            }
            return (
              <li key={i}><InlineContent text={item} highlightTerms={highlightTerms} /></li>
            );
          })}
        </Tag>
      );
    }

    case "paragraph":
      return <p><InlineContent text={block.content} highlightTerms={highlightTerms} /></p>;
  }
}

/* ------------------------------------------------------------------ */
/*  Inline parser + renderer                                           */
/* ------------------------------------------------------------------ */

type InlineNode =
  | { type: "text"; content: string }
  | { type: "code"; content: string }
  | { type: "bold"; content: string }
  | { type: "italic"; content: string }
  | { type: "strike"; content: string }
  | { type: "link"; text: string; href: string }
  | { type: "br" };

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  // Priority: code > link > bold > italic > strikethrough > bare URL > line break
  const pattern =
    /(`[^`]+`)|(\[([^\]]+)\]\(([^)]+)\))|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|~~([^~]+)~~|(\bhttps?:\/\/[^\s<>)\]]+)|(\n)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }

    if (match[1]) {
      nodes.push({ type: "code", content: match[1].slice(1, -1) });
    } else if (match[2]) {
      nodes.push({ type: "link", text: match[3], href: match[4] });
    } else if (match[5]) {
      nodes.push({ type: "bold", content: match[6] });
    } else if (match[7]) {
      nodes.push({ type: "italic", content: match[8] });
    } else if (match[9]) {
      nodes.push({ type: "strike", content: match[9] });
    } else if (match[10]) {
      nodes.push({ type: "link", text: match[10], href: match[10] });
    } else if (match[11]) {
      nodes.push({ type: "br" });
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push({ type: "text", content: text.slice(lastIndex) });
  }

  return nodes;
}

function InlineContent({ text, highlightTerms }: { text: string; highlightTerms?: string[] }) {
  const nodes = useMemo(() => parseInline(text), [text]);

  return (
    <>
      {nodes.map((node, i) => {
        switch (node.type) {
          case "text":
            return <HighlightedText key={i} text={node.content} terms={highlightTerms} />;
          case "code":
            return (
              <code key={i} className="bg-secondary/60 px-1.5 py-0.5 text-xs font-mono text-primary/90">
                {node.content}
              </code>
            );
          case "bold":
            return <strong key={i} className="font-semibold"><HighlightedText text={node.content} terms={highlightTerms} /></strong>;
          case "italic":
            return <em key={i}><HighlightedText text={node.content} terms={highlightTerms} /></em>;
          case "strike":
            return <del key={i} className="text-muted-foreground line-through"><HighlightedText text={node.content} terms={highlightTerms} /></del>;
          case "link":
            return (
              <a
                key={i}
                href={node.href}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline underline-offset-2 decoration-primary/30 hover:decoration-primary/60 transition-colors"
              >
                {node.text}
              </a>
            );
          case "br":
            return <br key={i} />;
        }
      })}
    </>
  );
}

/** Highlight search terms within a plain text string. */
function HighlightedText({ text, terms }: { text: string; terms?: string[] }) {
  if (!terms || terms.length === 0) return <>{text}</>;

  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const regex = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = text.split(regex);

  return (
    <>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-warning/30 text-warning px-0.5">{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}
