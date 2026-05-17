import { useEffect, useRef, useState } from "react";
import { Loader2, Plus, Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SlashCommandMenu } from "@/components/chat/SlashCommandMenu";

interface PromptBarProps {
  input: string;
  setInput: (v: string) => void;
  streaming: boolean;
  onSend: () => void;
  onStop: () => void;
  onUploadFiles?: (files: File[]) => Promise<void>;
  disabled?: boolean;
}

export function PromptBar({ input, setInput, streaming, onSend, onStop, onUploadFiles, disabled }: PromptBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showMenu, setShowMenu] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Resize textarea to content
  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 240) + "px";
  };

  useEffect(resize, [input]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMenu) {
      // Let SlashCommandMenu handle arrow keys / enter / escape
      if (["ArrowUp", "ArrowDown", "Escape"].includes(e.key)) return;
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        // Menu will intercept via its own keydown listener on the window
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
    if (e.key === "Escape") {
      setShowMenu(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setInput(val);
    // Show slash menu when text starts with /
    setShowMenu(val.startsWith("/"));
  };

  const handleSelect = (command: string) => {
    setInput(`/${command} `);
    setShowMenu(false);
    textareaRef.current?.focus();
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
          onSelect={handleSelect}
          onClose={() => setShowMenu(false)}
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
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={blocked}
          placeholder={streaming ? "Responding…" : uploading ? "Uploading…" : "Ask anything…"}
          rows={1}
          className="flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50 min-h-[40px] max-h-[240px] overflow-y-auto"
          style={{ height: "40px" }}
        />
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
