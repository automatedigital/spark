---
title: Vision & Image Paste
description: Paste images from your clipboard into the Spark CLI for multimodal vision analysis.
sidebar_label: Vision & Image Paste
sidebar_position: 7
---

# Vision & Image Paste

Copy a screenshot, diagram, or photo to your clipboard, paste it into Spark, and ask anything about it. Images go to the model as base64 content blocks — any vision-capable model can work with them.

## Paste an Image

1. Copy an image to your clipboard
2. Use one of the paste methods below
3. A `[ Image #1]` badge appears above the input box
4. Add your question and press Enter

You can attach multiple images before sending. Press `Ctrl+C` to clear them all.

Images are saved to `~/.spark/images/` as timestamped PNG files.

## How to Attach

### `/paste` — works everywhere

```
/paste
```

The safest, most reliable method. Works in every terminal, every environment.

### Alt+V — works in most terminals

Press `Alt+V` to pull an image from your clipboard. Alt key combos pass through most terminal emulators rather than being intercepted.

> **Not in VSCode's integrated terminal.** VSCode intercepts many `Alt+` shortcuts for its own UI. Use `/paste` instead.

### Ctrl+V — only if your clipboard has both text and an image

When an app copies text *and* an image together, pasting normally will also attach the image. If your clipboard has only an image (no text), Ctrl+V does nothing — terminals speak text only.

### Ctrl+V (Linux desktop only)

On Linux, the terminal paste shortcut is `Ctrl+Shift+V`, not `Ctrl+V`. So `Ctrl+V` sends a raw byte that Spark intercepts to check the clipboard. This only works on Linux desktops with X11 or Wayland clipboard access.

## Platform Compatibility

| Environment | `/paste` | Alt+V | Ctrl+V text+image |
|---|:---:|:---:|:---:|
| macOS Terminal / iTerm2 |  |  |  |
| Linux X11 desktop |  |  |  |
| Linux Wayland desktop |  |  |  |
| WSL2 (Windows Terminal) |  |  | ¹ |
| VSCode Terminal (local) |  |  | ¹ |
| VSCode Terminal (SSH) |  | ² | ² |
| SSH terminal (any) |  | ² | ² |

¹ Only works when the clipboard contains both text and an image  
² Remote clipboard is not accessible — see workarounds below

## Setup by Platform

### macOS

Nothing to install. Spark uses `osascript`, which is built in. For a small speed boost, optionally install `pngpaste`:

```bash
brew install pngpaste
```

### Linux (X11)

```bash
sudo apt install xclip       # Ubuntu/Debian
sudo dnf install xclip       # Fedora
sudo pacman -S xclip         # Arch
```

### Linux (Wayland)

```bash
sudo apt install wl-clipboard   # Ubuntu/Debian
sudo dnf install wl-clipboard   # Fedora
sudo pacman -S wl-clipboard     # Arch
```

Not sure which display server you're on?

```bash
echo $XDG_SESSION_TYPE   # "wayland", "x11", or "tty"
```

### WSL2

No setup needed. Spark detects WSL2 automatically and uses `powershell.exe` to read the Windows clipboard. No temp files or path conversion required.

If you're on WSLg (WSL2 with GUI support), Spark tries PowerShell first, then falls back to `wl-paste`. WSLg clipboard images arrive as BMP, which Spark converts to PNG via Pillow or ImageMagick automatically.

Verify it's working:

```bash
# Check WSL detection
grep -i microsoft /proc/version

# Check PowerShell is accessible
which powershell.exe

# Copy an image, then run:
powershell.exe -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::ContainsImage()"
# Should print "True"
```

## Working Over SSH

Clipboard paste doesn't work over SSH. The CLI runs on the remote machine, and clipboard tools there can only see that machine's clipboard — not yours.

**Workarounds:**

- **Upload the file** — `scp` it over, or drag-and-drop in VSCode's file explorer, then reference it by path
- **Use a URL** — if the image is online, just paste the URL in your message. The agent can call `vision_analyze` on any URL directly
- **X11 forwarding** — connect with `ssh -X` to bridge your local clipboard. Requires an X server on your end (XQuartz on macOS, native on Linux X11). Can be slow for large images
- **Use a messaging platform** — send the image through Telegram, Discord, Slack, or WhatsApp instead. No clipboard limitations apply there

## Supported Models

Any vision-capable model works. The image is sent in OpenAI's vision content format:

```json
{
  "type": "image_url",
  "image_url": {
    "url": "data:image/png;base64,..."
  }
}
```

This includes GPT-4 Vision, Claude with vision, Gemini, and multimodal open-source models via OpenRouter.

## Why Can't Terminals Paste Images Directly?

Terminals are text-based. When you press Ctrl+V, the terminal reads text from your clipboard, wraps it in bracketed-paste escape sequences, and sends it as a text stream. If the clipboard has only an image, there's no text to send — the terminal does nothing.

That's why Spark bypasses the terminal paste mechanism entirely and calls OS clipboard tools (`osascript`, `powershell.exe`, `xclip`, `wl-paste`) directly via subprocess to read image data independently.
