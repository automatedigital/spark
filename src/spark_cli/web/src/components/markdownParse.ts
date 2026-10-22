/**
 * Pure markdown parsing + memo helpers for the chat Markdown renderer.
 *
 * Kept separate from Markdown.tsx (which holds the React components) so these
 * functions can be unit-tested without a DOM and so the component file satisfies
 * react-refresh's "only export components" rule.
 */

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type CalloutKind = "NOTE" | "TIP" | "IMPORTANT" | "WARNING" | "CAUTION";

export type BlockNode =
  | { type: "literal"; content: string }
  | { type: "details"; summary: string; content: string; open: boolean }
  | { type: "code"; lang: string; content: string; closed?: boolean }
  | { type: "heading"; level: number; content: string }
  | { type: "hr" }
  | { type: "list"; ordered: boolean; items: string[]; start?: number }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "blockquote"; content: string }
  | { type: "callout"; kind: CalloutKind; content: string }
  | { type: "paragraph"; content: string };

export type InlineNode =
  | { type: "text"; content: string }
  | { type: "code"; content: string }
  | { type: "bold"; content: string }
  | { type: "italic"; content: string }
  | { type: "strike"; content: string }
  | { type: "link"; text: string; href: string }
  | { type: "media"; path: string }
  | { type: "br" };

export interface BlockProps {
  block: BlockNode;
  highlightTerms?: string[];
  live: boolean;
  showCursor?: boolean;
  safeMode?: boolean;
  defaultWrap?: boolean;
}

export interface MarkdownRenderSegment {
  kind: "markdown" | "plain";
  text: string;
  start: number;
  end: number;
  live: boolean;
}

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

function isTableStart(lines: string[], index: number): boolean {
  return (
    lines[index]?.trim().startsWith("|") &&
    index + 1 < lines.length &&
    isTableSeparator(lines[index + 1])
  );
}

/** Recognize only a complete marker on the first, dequoted line. */
export function parseCallout(content: string): Extract<BlockNode, { type: "callout" }> | null {
  const newline = content.indexOf("\n");
  const firstLine = newline < 0 ? content : content.slice(0, newline);
  const marker = firstLine.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t\r]*$/);
  if (!marker) return null;
  return {
    type: "callout",
    kind: marker[1] as CalloutKind,
    content: newline < 0 ? "" : content.slice(newline + 1),
  };
}

// Intentionally line-based and case-sensitive. No general HTML parsing, attributes,
// nested disclosures, or markup in summaries. Bodies use the existing Markdown.
const DETAILS_START = /^<details(?:\s|>|$)/;
const DETAILS_OPEN = /^<details( open)?>$/;
const DETAILS_CLOSE = "</details>";
const DETAILS_MAX_CHARS = 6_000;

function readDetails(lines: string[], start: number): { block: BlockNode; end: number } {
  let depth = 1;
  let fence = false;
  let nested = false;
  let extraSummary = false;
  let end = start + 1;
  for (; end < lines.length; end++) {
    const line = lines[end];
    if (line.startsWith("```")) fence = !fence;
    if (fence || line.startsWith("```")) continue;
    if (end > start + 1 && /^<\/?summary(?:\s|>|$)/.test(line)) extraSummary = true;
    if (DETAILS_START.test(line)) { depth++; nested = true; }
    if (line === DETAILS_CLOSE) {
      depth--;
      if (depth === 0) break;
    }
  }
  const closed = end < lines.length;
  const source = lines.slice(start, closed ? end + 1 : end).join("\n");
  const summary = lines[start + 1]?.match(/^<summary>([^<>]+)<\/summary>$/)?.[1];
  const body = lines.slice(start + 2, end).join("\n");
  const valid = closed && !nested && DETAILS_OPEN.test(lines[start]) &&
    summary?.trim() && source.length <= DETAILS_MAX_CHARS && !extraSummary;
  return {
    block: valid
      ? { type: "details", summary: summary!, content: body, open: lines[start] === "<details open>" }
      : { type: "literal", content: source },
    end: closed ? end + 1 : end,
  };
}

export function parseBlocks(text: string): BlockNode[] {
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
      // Preserve the existing parse boundary for malformed closing lines, but
      // only a bare closing fence makes this specific block diagram-eligible.
      const closed = i < lines.length && /^```\s*$/.test(lines[i]);
      i++; // skip closing ```
      blocks.push({ type: "code", lang, content: codeLines.join("\n"), closed });
      continue;
    }

    if (DETAILS_START.test(line)) {
      const details = readDetails(lines, i);
      blocks.push(details.block);
      i = details.end;
      continue;
    }

    // Table — need header + separator + at least one row
    if (isTableStart(lines, i)) {
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
      const content = bqLines.join("\n");
      blocks.push(parseCallout(content) ?? { type: "blockquote", content });
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
      const start = Number.parseInt(line.match(/^(\d+)/)?.[1] ?? "1", 10);
      while (i < lines.length && /^\d+[.)]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+[.)]\s/, ""));
        i++;
      }
      blocks.push({ type: "list", ordered: true, items, start });
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
      !DETAILS_START.test(lines[i]) &&
      !isTableStart(lines, i)
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

/**
 * Split point between the stable committed prefix and the live streaming tail.
 * The boundary is the position just after the last blank line that sits OUTSIDE
 * any fenced code block or details candidate, so `parseBlocks(prefix) ++ parseBlocks(tail)` is always
 * equivalent to `parseBlocks(content)` (blank lines are the only block separator
 * this parser uses, and fences/details can span them).
 * Single O(n) pass — no per-frame rescans.
 */
export function findStableBoundary(content: string): number {
  return stableBlankBoundaries(content).at(-1) ?? 0;
}

function stableBlankBoundaries(content: string): number[] {
  const boundaries: number[] = [];
  let insideFence = false;
  let detailsDepth = 0;
  let lineStart = 0;

  for (let i = 0; i <= content.length; i++) {
    if (i !== content.length && content[i] !== "\n") continue;
    const line = content.slice(lineStart, i);
    if (line.startsWith("```")) {
      insideFence = !insideFence;
    } else if (!insideFence) {
      if (DETAILS_START.test(line)) detailsDepth++;
      else if (line === DETAILS_CLOSE) detailsDepth = Math.max(0, detailsDepth - 1);
      else if (line === "" && detailsDepth === 0) boundaries.push(Math.min(content.length, i + 1));
    }
    lineStart = i + 1;
  }
  return boundaries;
}

function splitPlainSegments(
  text: string,
  offset: number,
  size: number,
  live: boolean,
): MarkdownRenderSegment[] {
  const segments: MarkdownRenderSegment[] = [];
  for (let start = 0; start < text.length; start += size) {
    const end = Math.min(text.length, start + size);
    segments.push({
      kind: "plain",
      text: text.slice(start, end),
      start: offset + start,
      end: offset + end,
      live,
    });
  }
  return segments;
}

export function splitStableMarkdownSegments(
  content: string,
  options: { targetSize?: number; maxSize?: number } = {},
): MarkdownRenderSegment[] {
  const targetSize = options.targetSize ?? 4_000;
  const maxSize = options.maxSize ?? 10_000;
  if (!content) return [];
  if (content.length <= targetSize) {
    return [{ kind: "markdown", text: content, start: 0, end: content.length, live: false }];
  }

  const boundaries = stableBlankBoundaries(content);
  const segments: MarkdownRenderSegment[] = [];
  let start = 0;
  let boundaryIdx = 0;

  while (start < content.length) {
    const minEnd = Math.min(content.length, start + targetSize);
    const maxEnd = Math.min(content.length, start + maxSize);
    let best = 0;

    while (boundaryIdx < boundaries.length && boundaries[boundaryIdx] <= start) {
      boundaryIdx++;
    }
    for (let i = boundaryIdx; i < boundaries.length && boundaries[i] <= maxEnd; i++) {
      best = boundaries[i];
      if (boundaries[i] >= minEnd) break;
    }

    const end = best > start ? best : maxEnd;
    segments.push({
      kind: "markdown",
      text: content.slice(start, end),
      start,
      end,
      live: false,
    });
    start = end;
  }

  return segments;
}

/**
 * Make a streaming tail safe to parse as markdown: an open ``` fence would
 * otherwise flip the tail between "code block" and "paragraph soup" per token.
 * Virtually closing the fence keeps an in-progress code block rendering as a
 * code block. The returned text is display-only — segment offsets keep
 * referring to the real content.
 */
export function stabilizeLiveTail(tail: string): string {
  let insideFence = false;
  let detailsDepth = 0;
  let lineStart = 0;
  for (let i = 0; i <= tail.length; i++) {
    if (i === tail.length || tail[i] === "\n") {
      const line = tail.slice(lineStart, i);
      if (line.startsWith("```")) insideFence = !insideFence;
      else if (!insideFence) {
        if (DETAILS_START.test(line)) detailsDepth++;
        else if (line === DETAILS_CLOSE) detailsDepth = Math.max(0, detailsDepth - 1);
      }
      lineStart = i + 1;
    }
  }
  return insideFence && detailsDepth === 0 ? `${tail}\n\`\`\`` : tail;
}

export function buildMarkdownRenderSegments(
  content: string,
  streaming: boolean,
  options: {
    chunkTargetSize?: number;
    chunkMaxSize?: number;
    liveTailSize?: number;
    liveTailCap?: number;
    streamingHeadSize?: number;
    streamingFullSize?: number;
    streamingLargeSize?: number;
    plainSegmentSize?: number;
  } = {},
): MarkdownRenderSegment[] {
  const chunkTargetSize = options.chunkTargetSize ?? 4_000;
  const chunkMaxSize = options.chunkMaxSize ?? 10_000;
  const liveTailSize = options.liveTailSize ?? 1_600;
  const liveTailCap = options.liveTailCap ?? 6_000;
  const streamingHeadSize = options.streamingHeadSize ?? 800;
  const streamingFullSize = options.streamingFullSize ?? 800;
  const streamingLargeSize = options.streamingLargeSize ?? 20_000;
  const plainSegmentSize = options.plainSegmentSize ?? 8_000;

  if (!content) return [];
  if (!streaming) {
    return splitStableMarkdownSegments(content, {
      targetSize: chunkTargetSize,
      maxSize: chunkMaxSize,
    });
  }

  if (content.length <= streamingFullSize) {
    return [{
      kind: "markdown",
      text: stabilizeLiveTail(content),
      start: 0,
      end: content.length,
      live: true,
    }];
  }

  if (content.length <= streamingLargeSize) {
    // Incremental streaming render: everything before the last blank line
    // outside a code fence is committed — chunked into stable markdown
    // segments that memoize and never re-parse as the tail grows. Only the
    // trailing partial block re-parses per flush, so streamed markdown looks
    // final as it arrives and row heights don't jump at turn end.
    const commitEnd = findStableBoundary(content);
    const tail = content.slice(commitEnd);
    if (tail.length <= liveTailCap) {
      const segments = commitEnd > 0
        ? splitStableMarkdownSegments(content.slice(0, commitEnd), {
            targetSize: chunkTargetSize,
            maxSize: chunkMaxSize,
          })
        : [];
      if (tail) {
        segments.push({
          kind: "markdown",
          text: stabilizeLiveTail(tail),
          start: commitEnd,
          end: content.length,
          live: true,
        });
      }
      return segments;
    }
    // Pathological tail (e.g. one giant unclosed block): fall through to the
    // windowed fallback below rather than re-parsing a huge tail per flush.
  }

  const headEnd = Math.min(streamingHeadSize, content.length);
  const tailStart = Math.max(headEnd, content.length - liveTailSize);
  const hiddenChars = Math.max(0, tailStart - headEnd);
  const segments: MarkdownRenderSegment[] = [
    {
      kind: "markdown",
      text: content.slice(0, headEnd),
      start: 0,
      end: headEnd,
      live: false,
    },
  ];
  if (hiddenChars > 0) {
    segments.push(...splitPlainSegments(
      `\n\n... ${hiddenChars.toLocaleString()} characters received; showing the live tail while streaming ...\n\n`,
      headEnd,
      plainSegmentSize,
      false,
    ));
  }
  segments.push({
    kind: "plain",
    text: content.slice(tailStart),
    start: tailStart,
    end: content.length,
    live: true,
  });
  return segments;
}

/* ------------------------------------------------------------------ */
/*  Memo equality                                                      */
/* ------------------------------------------------------------------ */

/** Structural equality for parsed blocks — drives MemoBlock so committed blocks
 *  skip re-render when the tail grows (parseBlocks returns fresh objects each
 *  frame, so reference equality would never hit). */
function blocksEqual(a: BlockNode, b: BlockNode): boolean {
  if (a.type !== b.type) return false;
  switch (a.type) {
    case "hr":
      return true;
    case "code": {
      const bb = b as typeof a;
      return a.lang === bb.lang && a.content === bb.content && a.closed === bb.closed;
    }
    case "heading": {
      const bb = b as typeof a;
      return a.level === bb.level && a.content === bb.content;
    }
    case "callout": {
      const bb = b as typeof a;
      return a.kind === bb.kind && a.content === bb.content;
    }
    case "details": {
      const bb = b as typeof a;
      return a.summary === bb.summary && a.content === bb.content && a.open === bb.open;
    }
    case "literal":
    case "blockquote":
    case "paragraph": {
      const bb = b as typeof a;
      return a.content === bb.content;
    }
    case "list": {
      const bb = b as typeof a;
      return (
        a.ordered === bb.ordered &&
        a.items.length === bb.items.length &&
        a.items.every((it, i) => it === bb.items[i])
      );
    }
    case "table": {
      const bb = b as typeof a;
      return (
        a.headers.length === bb.headers.length &&
        a.headers.every((h, i) => h === bb.headers[i]) &&
        a.rows.length === bb.rows.length &&
        a.rows.every(
          (row, i) =>
            row.length === bb.rows[i].length &&
            row.every((c, j) => c === bb.rows[i][j]),
        )
      );
    }
  }
}

function termsEqual(a?: string[], b?: string[]): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every((t, i) => t === b[i]);
}

/** React.memo comparator for a rendered block. Returns true (skip re-render)
 *  when a block is structurally unchanged and not the live streaming block —
 *  this is what stops committed blocks from re-rendering as the tail grows. */
export function blockPropsEqual(prev: BlockProps, next: BlockProps): boolean {
  return (
    prev.live === next.live &&
    prev.showCursor === next.showCursor &&
    prev.safeMode === next.safeMode &&
    prev.defaultWrap === next.defaultWrap &&
    termsEqual(prev.highlightTerms, next.highlightTerms) &&
    blocksEqual(prev.block, next.block)
  );
}

/* ------------------------------------------------------------------ */
/*  Inline parser                                                      */
/* ------------------------------------------------------------------ */

export function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  // Priority: MEDIA > code > link > bold > italic > strikethrough > bare URL > line break
  // NOTE: the media-path alternative uses a single lazy `[^\n]*?` rather than the
  // nested `\S+(?:[^\S\n]+\S+)*?` quantifier it replaced — the latter is a
  // catastrophic-backtracking shape that could hang the renderer on adversarial
  // input following a literal "MEDIA:". `[^\n]*?` is linear. Capture-group
  // numbering is unchanged.
  const pattern =
    /[`"']?MEDIA:\s*(`[^`\n]+`|"[^"\n]+"|'[^'\n]+'|(?:~?\/|[A-Za-z]:\\)[^\n]*?\.(?:png|jpe?g|gif|webp|mp4|mov|avi|mkv|webm|ogg|opus|mp3|wav|m4a)(?=[\s`"',;:)\]}]|$)|\S+)[`"']?|(`[^`]+`)|(\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\))|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|~~([^~]+)~~|(\bhttps?:\/\/[^\s<]+)|(\n)/gi;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push({ type: "text", content: text.slice(lastIndex, match.index) });
    }

    if (match[1]) {
      nodes.push({ type: "media", path: cleanMediaPath(match[1]) });
    } else if (match[2]) {
      nodes.push({ type: "code", content: match[2].slice(1, -1) });
    } else if (match[3]) {
      nodes.push({ type: "link", text: match[4], href: match[5] });
    } else if (match[6]) {
      nodes.push({ type: "bold", content: match[7] });
    } else if (match[8]) {
      nodes.push({ type: "italic", content: match[9] });
    } else if (match[10]) {
      nodes.push({ type: "strike", content: match[10] });
    } else if (match[11]) {
      const { href, trailing } = splitTrailingUrlPunctuation(match[11]);
      nodes.push({ type: "link", text: href, href });
      if (trailing) nodes.push({ type: "text", content: trailing });
    } else if (match[12]) {
      nodes.push({ type: "br" });
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push({ type: "text", content: text.slice(lastIndex) });
  }

  return nodes;
}

function splitTrailingUrlPunctuation(url: string): { href: string; trailing: string } {
  let href = url;
  let trailing = "";
  const moveTrailing = () => {
    trailing = href[href.length - 1] + trailing;
    href = href.slice(0, -1);
  };

  while (href && /[.,;:!?]/.test(href[href.length - 1])) {
    moveTrailing();
  }

  const pairs: Record<string, string> = { ")": "(", "]": "[", "}": "{" };
  while (href && pairs[href[href.length - 1]]) {
    const close = href[href.length - 1];
    const open = pairs[close];
    const opens = [...href].filter((char) => char === open).length;
    const closes = [...href].filter((char) => char === close).length;
    if (closes <= opens) break;
    moveTrailing();
  }

  return { href, trailing };
}

export function cleanMediaPath(path: string): string {
  let cleaned = path.trim();
  if (cleaned.length >= 2 && "`\"'".includes(cleaned[0]) && cleaned[0] === cleaned[cleaned.length - 1]) {
    cleaned = cleaned.slice(1, -1).trim();
  }
  return cleaned.replace(/^[`"']+|[`"',.;:)}\]]+$/g, "");
}

export function mediaKind(path: string): "image" | "video" | "audio" | "file" {
  const ext = path.split("?")[0].split(".").pop()?.toLowerCase() ?? "";
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) return "image";
  if (["mp4", "mov", "avi", "mkv", "webm"].includes(ext)) return "video";
  if (["ogg", "opus", "mp3", "wav", "m4a"].includes(ext)) return "audio";
  return "file";
}
