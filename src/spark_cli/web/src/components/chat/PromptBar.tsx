import { useEffect, useRef, useState } from "react";
import { Loader2, Plus, Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SlashCommandMenu } from "@/components/chat/SlashCommandMenu";
import { AtFileMenu } from "@/components/chat/AtFileMenu";

interface PromptBarProps {
  input: string;
  setInput: (v: string) => void;
  streaming: boolean;
  onSend: () => void;
  onStop: () => void;
  onUploadFiles?: (files: File[]) => Promise<void>;
  disabled?: boolean;
  workspaceSlug?: string;
}

// Match @tokens and /commands at line start (gm: ^ matches after each \n)
const TOKEN_RE = /(@\S+)|(^\/\S+)/gm;

function renderMirror(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    nodes.push(
      <mark key={m.index} className="bg-transparent text-primary font-medium not-italic">
        {m[0]}
      </mark>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  // Trailing space prevents div collapse when text ends with \n
  nodes.push(" ");
  return nodes;
}

export function PromptBar({
  input,
  setInput,
  streaming,
  onSend,
  onStop,
  onUploadFiles,
  disabled,
  workspaceSlug,
}: PromptBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showMenu, setShowMenu] = useState(false);
  const [showAtMenu, setShowAtMenu] = useState(false);
  const [atQuery, setAtQuery] = useState("");
  const [uploading, setUploading] = useState(false);

  // Resize textarea to content
  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 240) + "px";
  };

  useEffect(resize, [input]);

  const syncScroll = () => {
    if (mirrorRef.current && textareaRef.current) {
      mirrorRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMenu || showAtMenu) {
      // Let the active menu handle arrow keys / enter / escape / tab
      if (["ArrowUp", "ArrowDown", "Escape"].includes(e.key)) return;
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
    if (e.key === "Escape") {
      setShowMenu(false);
      setShowAtMenu(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    const cursor = e.target.selectionStart ?? val.length;
    setInput(val);

    // Slash command menu: only when input starts with /
    setShowMenu(val.startsWith("/"));

    // @ file menu: detect @token immediately before cursor
    const beforeCursor = val.slice(0, cursor);
    const atMatch = /(@\S*)$/.exec(beforeCursor);
    if (atMatch) {
      setAtQuery(atMatch[1].slice(1)); // strip the leading @
      setShowAtMenu(true);
    } else {
      setShowAtMenu(false);
    }
  };

  const handleSlashSelect = (command: string) => {
    setInput(`/${command} `);
    setShowMenu(false);
    textareaRef.current?.focus();
  };

  const handleAtSelect = (path: string, isDir: boolean) => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const cursor = textarea.selectionStart ?? input.length;
    const beforeCursor = input.slice(0, cursor);
    const atMatch = /(@\S*)$/.exec(beforeCursor);
    if (!atMatch) return;

    const atStart = cursor - atMatch[0].length;
    // Dirs get a trailing slash so user can keep browsing; files get a space to close the token
    const newToken = `@${path}${isDir ? "/" : " "}`;
    const newInput = input.slice(0, atStart) + newToken + input.slice(cursor);
    setInput(newInput);

    if (isDir) {
      setAtQuery(`${path}/`);
    } else {
      setShowAtMenu(false);
    }

    // Restore cursor after the completed token
    setTimeout(() => {
      const pos = atStart + newToken.length;
      textarea.selectionStart = textarea.selectionEnd = pos;
      textarea.focus();
    }, 0);
  };

  const handleFilesSelected = async (files: FileList | null) => {
    if (!files || !onUploadFiles) return;
    const arr = Array.from(files);
    if (!arr.length) return;
    setUploading(true);
    try {
      await onUploadFiles(arr);
      textareaRef.current?.focus();
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const charCount = input.length;
  const blocked = disabled || streaming || uploading;

  return (
    <div className="border-t border-border px-4 py-3 shrink-0 relative">
      {showMenu && (
        <SlashCommandMenu
          query={input.slice(1)} // strip leading /
          onSelect={handleSlashSelect}
          onClose={() => setShowMenu(false)}
        />
      )}
      {showAtMenu && (
        <AtFileMenu
          query={atQuery}
          workspaceSlug={workspaceSlug}
          onSelect={handleAtSelect}
          onClose={() => setShowAtMenu(false)}
        />
      )}

      <div
        className={`flex gap-2 items-end rounded-md border transition-shadow ${
          input.split("\n").length > 1 || input.length > 80
            ? "shadow-[0_-2px_8px_rgba(0,0,0,0.3)]"
            : ""
        } border-transparent`}
      >
        {onUploadFiles && (
          <>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-10 w-10 shrink-0"
              disabled={blocked}
              onClick={() => fileInputRef.current?.click()}
              title="Add file"
            >
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => void handleFilesSelected(e.target.files)}
            />
          </>
        )}

        {/* Rich input: mirror div for highlights + transparent textarea on top */}
        <div
          className={`relative flex-1 rounded-md border border-input bg-background min-h-[40px] focus-within:ring-1 focus-within:ring-ring transition-opacity ${
            blocked ? "opacity-50" : ""
          }`}
        >
          <div
            ref={mirrorRef}
            aria-hidden
            className="absolute inset-0 pointer-events-none overflow-hidden px-3 py-2 text-sm text-foreground whitespace-pre-wrap break-words select-none"
          >
            {renderMirror(input)}
          </div>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onScroll={syncScroll}
            disabled={blocked}
            placeholder={streaming ? "Responding…" : uploading ? "Uploading…" : "Ask anything…"}
            rows={1}
            className="relative z-10 w-full resize-none bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed min-h-[40px] max-h-[240px] overflow-y-auto"
            style={{ height: "40px", color: "transparent", caretColor: "hsl(var(--foreground))" }}
          />
        </div>

        <div className="flex flex-col items-end gap-1 shrink-0">
          {streaming ? (
            <Button
              size="icon"
              variant="destructive"
              className="h-10 w-10"
              onClick={onStop}
              title="Stop"
            >
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              className="h-10 w-10"
              disabled={!input.trim() || !!disabled || uploading}
              onClick={onSend}
              title="Send (Enter)"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
          {charCount > 200 && (
            <span className="text-[9px] text-muted-foreground tabular-nums">{charCount}</span>
          )}
        </div>
      </div>
    </div>
  );
}
