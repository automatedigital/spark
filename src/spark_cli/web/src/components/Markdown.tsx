import { memo, useMemo, useState } from "react";
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
import { Copy, CheckCheck, X } from "lucide-react";
import { mediaFileUrl } from "@/lib/api";
import {
  type BlockNode,
  type BlockProps,
  parseBlocks,
  parseInline,
  findStableBoundary,
  blockPropsEqual,
  mediaKind,
} from "./markdownParse";

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
 *
 * Parsing + memo helpers live in ./markdownParse so they can be unit-tested
 * without a DOM. This file holds only the React components.
 */

// Above this size we stop doing expensive block/inline markdown work. The user
// still gets the complete response text, but we avoid repeatedly feeding very
// large assistant messages through regex-heavy parsing in WebKit.
const SOFT_RENDER_CAP = 6_000;

export const Markdown = memo(function Markdown({
  content,
  highlightTerms,
  streaming = false,
  safeMode = false,
}: {
  content: string;
  highlightTerms?: string[];
  streaming?: boolean;
  safeMode?: boolean;
}) {
  if (safeMode || streaming || content.length > SOFT_RENDER_CAP) {
    return (
      <div
        role="article"
        aria-label={streaming ? "Streaming assistant response" : "Full assistant response"}
        className="w-full min-w-0 max-w-full whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground"
      >
        {content}
      </div>
    );
  }

  return <ParsedMarkdown content={content} highlightTerms={highlightTerms} streaming={streaming} safeMode={safeMode} />;
});

function ParsedMarkdown({
  content,
  highlightTerms,
  streaming,
  safeMode,
}: {
  content: string;
  highlightTerms?: string[];
  streaming: boolean;
  safeMode: boolean;
}) {
  // Split the message into a stable, already-committed prefix and a small live
  // "tail" that is still streaming in. Only the tail is re-parsed on each
  // animation frame, and committed blocks are memoized so they don't re-render —
  // so per-frame cost stays bounded no matter how long the full message grows.
  // This is what keeps the webview from pinning a CPU core on long
  // web-search / delegation responses.
  const boundary = useMemo(() => findStableBoundary(content), [content]);
  const stablePart = content.slice(0, boundary);
  const tailPart = content.slice(boundary);

  const stableBlocks = useMemo(() => parseBlocks(stablePart), [stablePart]);
  const tailBlocks = useMemo(() => parseBlocks(tailPart), [tailPart]);

  const total = stableBlocks.length + tailBlocks.length;
  return (
    <div className="text-sm text-foreground leading-relaxed space-y-2">
      {stableBlocks.map((block, i) => (
        <MemoBlock key={i} block={block} highlightTerms={safeMode ? undefined : highlightTerms} live={false} safeMode={safeMode} />
      ))}
      {tailBlocks.map((block, i) => {
        const idx = stableBlocks.length + i;
        return (
          <MemoBlock
            key={idx}
            block={block}
            highlightTerms={safeMode ? undefined : highlightTerms}
            live={streaming && idx === total - 1}
            safeMode={safeMode}
          />
        );
      })}
    </div>
  );
}

const MemoBlock = memo(function MemoBlock({ block, highlightTerms, live, safeMode }: BlockProps) {
  return <Block block={block} highlightTerms={highlightTerms} live={live} safeMode={safeMode} />;
}, blockPropsEqual);

/* ------------------------------------------------------------------ */
/*  Code block with syntax highlight + copy button                    */
/* ------------------------------------------------------------------ */

function CodeBlock({ lang, content, live, safeMode }: { lang: string; content: string; live?: boolean; safeMode?: boolean }) {
  const [copied, setCopied] = useState(false);

  const highlighted = useMemo(() => {
    // Defer syntax highlighting while the block is still streaming in — hljs is
    // O(n) and re-running it every frame on a growing code block is O(n²).
    // Render plain text now; highlight once the block is complete (live=false).
    if (live || safeMode || content.length > 24_000) return null;
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(content, { language: lang }).value;
      } catch {
        /* fall through */
      }
    }
    return null;
  }, [lang, content, live, safeMode]);

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

function Block({ block, highlightTerms, live, safeMode }: { block: BlockNode; highlightTerms?: string[]; live?: boolean; safeMode?: boolean }) {
  switch (block.type) {
    case "code":
      return <CodeBlock lang={block.lang} content={block.content} live={live} safeMode={safeMode} />;

    case "heading": {
      const Tag = `h${Math.min(block.level, 4)}` as "h1" | "h2" | "h3" | "h4";
      const sizes: Record<string, string> = {
        h1: "text-base font-bold",
        h2: "text-sm font-bold",
        h3: "text-sm font-semibold",
        h4: "text-sm font-medium",
      };
      return <Tag className={sizes[Tag]}><InlineContent text={block.content} highlightTerms={highlightTerms} safeMode={safeMode} /></Tag>;
    }

    case "hr":
      return <hr className="border-border" />;

    case "blockquote":
      return (
        <blockquote className="border-l-2 border-primary/40 pl-3 text-muted-foreground italic bg-secondary/20 py-1 rounded-r-sm">
          <InlineContent text={block.content} highlightTerms={highlightTerms} safeMode={safeMode} />
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
                    <InlineContent text={h} highlightTerms={highlightTerms} safeMode={safeMode} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 0 ? "bg-background" : "bg-secondary/20"}>
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3 py-1.5 border-t border-border/30 text-foreground/90">
                      <InlineContent text={cell} highlightTerms={highlightTerms} safeMode={safeMode} />
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
                    <InlineContent text={taskMatch[2]} highlightTerms={highlightTerms} safeMode={safeMode} />
                  </span>
                </li>
              );
            }
            return (
              <li key={i}><InlineContent text={item} highlightTerms={highlightTerms} safeMode={safeMode} /></li>
            );
          })}
        </Tag>
      );
    }

    case "paragraph":
      return <p><InlineContent text={block.content} highlightTerms={highlightTerms} safeMode={safeMode} /></p>;
  }
}

/* ------------------------------------------------------------------ */
/*  Inline renderer                                                    */
/* ------------------------------------------------------------------ */

function MediaPreview({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const kind = mediaKind(path);
  const src = mediaFileUrl(path);
  const name = path.split(/[\\/]/).pop() || "media";

  if (kind === "image") {
    return (
      <span className="my-2 block">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="block overflow-hidden rounded-md border border-border/70 bg-background/40 transition-colors hover:border-primary/60"
          title={`Preview ${name}`}
        >
          <img src={src} alt={name} className="max-h-72 max-w-full object-contain" loading="lazy" />
        </button>
        {open ? (
          <span
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-6"
            role="dialog"
            aria-modal="true"
            onClick={() => setOpen(false)}
          >
            <button
              type="button"
              className="absolute right-4 top-4 rounded-full bg-background/90 p-2 text-foreground shadow-lg"
              title="Close preview"
              onClick={() => setOpen(false)}
            >
              <X className="h-5 w-5" />
            </button>
            <img
              src={src}
              alt={name}
              className="max-h-full max-w-full rounded-md object-contain shadow-2xl"
              onClick={(event) => event.stopPropagation()}
            />
          </span>
        ) : null}
      </span>
    );
  }

  if (kind === "video") {
    return (
      <span className="my-2 block">
        <video src={src} controls className="max-h-80 max-w-full rounded-md border border-border/70 bg-black" />
      </span>
    );
  }

  if (kind === "audio") {
    return (
      <span className="my-2 block">
        <audio src={src} controls className="w-full max-w-md" />
      </span>
    );
  }

  return (
    <a
      href={src}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline underline-offset-2 decoration-primary/30 hover:decoration-primary/60 transition-colors"
    >
      {name}
    </a>
  );
}

function InlineContent({ text, highlightTerms, safeMode }: { text: string; highlightTerms?: string[]; safeMode?: boolean }) {
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
            return <strong key={i} className="font-semibold"><InlineContent text={node.content} highlightTerms={highlightTerms} safeMode={safeMode} /></strong>;
          case "italic":
            return <em key={i}><InlineContent text={node.content} highlightTerms={highlightTerms} safeMode={safeMode} /></em>;
          case "strike":
            return <del key={i} className="text-muted-foreground line-through"><InlineContent text={node.content} highlightTerms={highlightTerms} safeMode={safeMode} /></del>;
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
          case "media":
            return safeMode ? (
              <code key={i} className="bg-secondary/60 px-1.5 py-0.5 text-xs font-mono text-primary/90">
                MEDIA: {node.path}
              </code>
            ) : (
              <MediaPreview key={i} path={node.path} />
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
