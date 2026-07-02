import { memo, useMemo, useState, type MouseEvent } from "react";
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
import { Copy, CheckCheck, X, FileText, ExternalLink, FolderOpen, Loader2, WrapText } from "lucide-react";
import { api, mediaFileUrl, openExternal } from "@/lib/api";
import { setGlobalNavTarget } from "@/lib/globalNavigation";
import { isTauri } from "@/sidecar";
import {
  type BlockNode,
  type BlockProps,
  type MarkdownRenderSegment,
  parseBlocks,
  parseInline,
  blockPropsEqual,
  mediaKind,
  buildMarkdownRenderSegments,
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

const LARGE_INLINE_PLAIN_CHARS = 20_000;
const LOCAL_FILE_PATH_PATTERN =
  /(?:~|\/(?:Users|private|var|tmp|Volumes|home|opt|usr|etc|mnt|workspace|[A-Za-z0-9._-]+))[^\s`"'<>]*\.(?:md|markdown|txt|json|yaml|yml|csv|log|py|ts|tsx|js|jsx|html|css|scss|sql|sh|zsh|toml|xml|pdf|png|jpe?g|gif|webp|svg)/gi;

export const Markdown = memo(function Markdown({
  content,
  highlightTerms,
  streaming = false,
  safeMode = false,
  renderRevision,
  defaultWrap = false,
}: {
  content: string;
  highlightTerms?: string[];
  streaming?: boolean;
  safeMode?: boolean;
  renderRevision?: number;
  defaultWrap?: boolean;
}) {
  if (safeMode || streaming || content.length > LARGE_INLINE_PLAIN_CHARS) {
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

  return (
    <ParsedMarkdown
      content={content}
      highlightTerms={highlightTerms}
      streaming={streaming}
      safeMode={safeMode}
      renderRevision={renderRevision}
      defaultWrap={defaultWrap}
    />
  );
}, (prev, next) => (
  prev.content === next.content &&
  prev.streaming === next.streaming &&
  prev.safeMode === next.safeMode &&
  prev.renderRevision === next.renderRevision &&
  prev.defaultWrap === next.defaultWrap &&
  termsEqual(prev.highlightTerms, next.highlightTerms)
));

function ParsedMarkdown({
  content,
  highlightTerms,
  streaming,
  safeMode,
  renderRevision,
  defaultWrap,
}: {
  content: string;
  highlightTerms?: string[];
  streaming: boolean;
  safeMode: boolean;
  renderRevision?: number;
  defaultWrap: boolean;
}) {
  const segments = useMemo(
    () => buildMarkdownRenderSegments(content, streaming),
    [content, streaming, renderRevision],
  );

  return (
    <div className="text-sm text-foreground leading-relaxed space-y-2">
      {segments.map((segment) => (
        segment.kind === "plain" ? (
          <MemoPlainSegment key={`${segment.kind}:${segment.start}:${segment.end}`} segment={segment} />
        ) : (
          <MemoMarkdownSegment
            key={`${segment.kind}:${segment.start}:${segment.end}`}
            segment={segment}
            highlightTerms={safeMode ? undefined : highlightTerms}
            safeMode={safeMode}
            defaultWrap={defaultWrap}
          />
        )
      ))}
    </div>
  );
}

const MemoPlainSegment = memo(function PlainSegment({ segment }: { segment: MarkdownRenderSegment }) {
  return (
    <div className="whitespace-pre-wrap break-words text-foreground/90">
      {segment.text}
    </div>
  );
}, (prev, next) => (
  prev.segment.text === next.segment.text &&
  prev.segment.start === next.segment.start &&
  prev.segment.end === next.segment.end
));

const MemoMarkdownSegment = memo(function MarkdownSegment({
  segment,
  highlightTerms,
  safeMode,
  defaultWrap,
}: {
  segment: MarkdownRenderSegment;
  highlightTerms?: string[];
  safeMode?: boolean;
  defaultWrap?: boolean;
}) {
  const blocks = useMemo(() => parseBlocks(segment.text), [segment.text]);
  const total = blocks.length;
  return (
    <>
      {blocks.map((block, i) => (
        <MemoBlock
          key={i}
          block={block}
          highlightTerms={safeMode ? undefined : highlightTerms}
          live={segment.live && i === total - 1}
          safeMode={safeMode}
          defaultWrap={defaultWrap}
        />
      ))}
    </>
  );
}, (prev, next) => (
  prev.segment.text === next.segment.text &&
  prev.segment.start === next.segment.start &&
  prev.segment.end === next.segment.end &&
  prev.segment.live === next.segment.live &&
  prev.safeMode === next.safeMode &&
  prev.defaultWrap === next.defaultWrap &&
  termsEqual(prev.highlightTerms, next.highlightTerms)
));

const MemoBlock = memo(function MemoBlock({ block, highlightTerms, live, safeMode, defaultWrap }: BlockProps) {
  return <Block block={block} highlightTerms={highlightTerms} live={live} safeMode={safeMode} defaultWrap={defaultWrap} />;
}, blockPropsEqual);

/* ------------------------------------------------------------------ */
/*  Code block with syntax highlight + copy button                    */
/* ------------------------------------------------------------------ */

function WrapToggleButton({
  wrapped,
  onToggle,
  label,
}: {
  wrapped: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={label}
      aria-pressed={wrapped}
      className={`inline-flex h-6 w-6 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:text-foreground ${
        wrapped ? "bg-foreground/10 text-foreground" : ""
      }`}
      title={label}
    >
      <WrapText className="h-3.5 w-3.5" />
    </button>
  );
}

function CodeBlock({
  lang,
  content,
  live,
  safeMode,
  defaultWrap = false,
}: {
  lang: string;
  content: string;
  live?: boolean;
  safeMode?: boolean;
  defaultWrap?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [wrapped, setWrapped] = useState(defaultWrap);

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
        <span className="flex items-center gap-1">
          <WrapToggleButton
            wrapped={wrapped}
            onToggle={() => setWrapped((value) => !value)}
            label={wrapped ? "Disable code word wrap" : "Enable code word wrap"}
          />
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
        </span>
      </div>
      {highlighted ? (
        <pre className={`bg-secondary/40 px-3 py-2.5 text-xs font-mono leading-relaxed hljs ${
          wrapped ? "whitespace-pre-wrap break-words overflow-x-hidden" : "overflow-x-auto"
        }`}>
          <code dangerouslySetInnerHTML={{ __html: highlighted }} />
        </pre>
      ) : (
        <pre className={`bg-secondary/40 px-3 py-2.5 text-xs font-mono leading-relaxed ${
          wrapped ? "whitespace-pre-wrap break-words overflow-x-hidden" : "overflow-x-auto"
        }`}>
          <code>{content}</code>
        </pre>
      )}
    </div>
  );
}

function TableBlock({
  headers,
  rows: rawRows,
  live,
  highlightTerms,
  safeMode,
  defaultWrap = false,
}: {
  headers: string[];
  rows: string[][];
  live?: boolean;
  highlightTerms?: string[];
  safeMode?: boolean;
  defaultWrap?: boolean;
}) {
  const [wrapped, setWrapped] = useState(defaultWrap);
  const MAX_LIVE_TABLE_ROWS = 80;
  const MAX_LIVE_TABLE_CELLS = 8;
  const rows = live ? rawRows.slice(0, MAX_LIVE_TABLE_ROWS) : rawRows;
  const visibleHeaders = live ? headers.slice(0, MAX_LIVE_TABLE_CELLS) : headers;
  const hiddenRows = rawRows.length - rows.length;
  const renderRow = (row: string[]) => (live ? row.slice(0, MAX_LIVE_TABLE_CELLS) : row);
  const cellWrapClass = wrapped ? "whitespace-normal break-words align-top" : "whitespace-nowrap";

  return (
    <div className="overflow-hidden rounded-md border border-border/60">
      <div className="flex items-center justify-between border-b border-border/40 bg-secondary/80 px-3 py-1">
        <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
          Table
        </span>
        <WrapToggleButton
          wrapped={wrapped}
          onToggle={() => setWrapped((value) => !value)}
          label={wrapped ? "Disable table word wrap" : "Enable table word wrap"}
        />
      </div>
      <div className={wrapped ? "overflow-x-hidden" : "overflow-x-auto"}>
        <table className={`w-full text-xs border-collapse ${wrapped ? "table-fixed" : ""}`}>
          <thead>
            <tr className="bg-secondary/60 border-b border-border/60">
              {visibleHeaders.map((h, i) => (
                <th key={i} className={`px-3 py-2 text-left font-semibold text-foreground ${cellWrapClass}`}>
                  <InlineContent text={h} highlightTerms={highlightTerms} safeMode={safeMode} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 0 ? "bg-background" : "bg-secondary/20"}>
                {renderRow(row).map((cell, ci) => (
                  <td key={ci} className={`px-3 py-1.5 border-t border-border/30 text-foreground/90 ${cellWrapClass}`}>
                    <InlineContent text={cell} highlightTerms={highlightTerms} safeMode={safeMode} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hiddenRows > 0 && (
        <div className="border-t border-border/40 bg-secondary/30 px-3 py-1.5 text-[11px] text-muted-foreground">
          Showing first {rows.length} rows while streaming.
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Block renderer                                                     */
/* ------------------------------------------------------------------ */

function Block({
  block,
  highlightTerms,
  live,
  safeMode,
  defaultWrap,
}: {
  block: BlockNode;
  highlightTerms?: string[];
  live?: boolean;
  safeMode?: boolean;
  defaultWrap?: boolean;
}) {
  switch (block.type) {
    case "code":
      return <CodeBlock lang={block.lang} content={block.content} live={live} safeMode={safeMode} defaultWrap={defaultWrap} />;

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
        <TableBlock
          headers={block.headers}
          rows={block.rows}
          live={live}
          highlightTerms={highlightTerms}
          safeMode={safeMode}
          defaultWrap={defaultWrap}
        />
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

function isLocalFilePath(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)) return false;
  LOCAL_FILE_PATH_PATTERN.lastIndex = 0;
  const match = LOCAL_FILE_PATH_PATTERN.exec(trimmed);
  return Boolean(match && match.index === 0 && match[0].length === trimmed.length);
}

function splitLocalFilePaths(text: string): Array<{ kind: "text"; value: string } | { kind: "file"; value: string }> {
  const parts: Array<{ kind: "text"; value: string } | { kind: "file"; value: string }> = [];
  LOCAL_FILE_PATH_PATTERN.lastIndex = 0;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = LOCAL_FILE_PATH_PATTERN.exec(text))) {
    if (match.index > last) parts.push({ kind: "text", value: text.slice(last, match.index) });
    parts.push({ kind: "file", value: match[0] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", value: text.slice(last) });
  return parts;
}

function FilePathAction({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const name = path.split(/[\\/]/).pop() || "file";
  const rawUrl = mediaFileUrl(path);

  const handleOpen = () => {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (!nextOpen || content !== null || loading) return;
    setLoading(true);
    setError(null);
    void api.readChatFile(path)
      .then((text) => setContent(text))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not open file"))
      .finally(() => setLoading(false));
  };

  const handleRawClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isTauri()) return;
    event.preventDefault();
    void openExternal(rawUrl);
  };

  const handleOpenInFiles = () => {
    setGlobalNavTarget({ type: "file", path, name });
  };

  return (
    <span className="my-1 inline-block max-w-full align-middle">
      <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium text-primary shadow-sm transition-colors hover:border-primary/60 hover:bg-primary/15">
        <button
          type="button"
          onClick={handleOpen}
          className="inline-flex min-w-0 items-center gap-1.5"
          title={`Open ${path}`}
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" /> : <FileText className="h-3.5 w-3.5 shrink-0" />}
          <span className="truncate">{name}</span>
        </button>
        <a
          href={rawUrl}
          target="_blank"
          rel="noreferrer"
          onClick={handleRawClick}
          className="shrink-0 text-primary/70 transition-colors hover:text-primary"
          title="Open raw file"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
        <button
          type="button"
          onClick={handleOpenInFiles}
          className="inline-flex shrink-0 items-center gap-1 rounded-sm border-l border-primary/25 pl-1.5 text-primary/80 transition-colors hover:text-primary"
          title="Open in Files"
        >
          <FolderOpen className="h-3.5 w-3.5" />
          <span>Files</span>
        </button>
      </span>
      {open ? (
        <span className="mt-2 block max-w-full overflow-hidden rounded-md border border-border/70 bg-background/75">
          <span className="flex items-center justify-between gap-3 border-b border-border/50 bg-secondary/50 px-3 py-1.5">
            <span className="min-w-0 truncate text-xs font-medium text-foreground">{name}</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
              title="Close file preview"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
          <span className="block px-3 py-2">
            {loading ? (
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Opening file...
              </span>
            ) : error ? (
              <span className="text-xs text-destructive">{error}</span>
            ) : (
              <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-foreground/90">{content ?? ""}</pre>
            )}
          </span>
        </span>
      ) : null}
    </span>
  );
}

function openLinkInDesktop(event: MouseEvent<HTMLAnchorElement>, href: string) {
  if (!isTauri() || !/^https?:\/\//i.test(href)) return;
  event.preventDefault();
  void openExternal(href);
}

function InlineContent({ text, highlightTerms, safeMode }: { text: string; highlightTerms?: string[]; safeMode?: boolean }) {
  const nodes = useMemo(() => parseInline(text), [text]);

  return (
    <>
      {nodes.map((node, i) => {
        switch (node.type) {
          case "text":
            return <TextWithFileActions key={i} text={node.content} terms={highlightTerms} safeMode={safeMode} />;
          case "code":
            if (!safeMode && isLocalFilePath(node.content)) {
              return <FilePathAction key={i} path={node.content.trim()} />;
            }
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
                onClick={(event) => openLinkInDesktop(event, node.href)}
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

function TextWithFileActions({ text, terms, safeMode }: { text: string; terms?: string[]; safeMode?: boolean }) {
  if (safeMode) return <HighlightedText text={text} terms={terms} />;
  const parts = splitLocalFilePaths(text);
  if (parts.length === 1 && parts[0].kind === "text") {
    return <HighlightedText text={text} terms={terms} />;
  }
  return (
    <>
      {parts.map((part, i) => (
        part.kind === "file" ? (
          <FilePathAction key={i} path={part.value} />
        ) : (
          <HighlightedText key={i} text={part.value} terms={terms} />
        )
      ))}
    </>
  );
}

function termsEqual(a?: string[], b?: string[]): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every((t, i) => t === b[i]);
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
