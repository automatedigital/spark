---
sidebar_position: 10
title: "Skins & Themes"
description: "Customize the Spark CLI with built-in and user-defined skins"
---

# Skins & Themes

Change how Spark looks without touching its behavior. Skins control the visual presentation of the CLI: banner colors, spinner faces and verbs, response-box labels, branding text, and the tool activity prefix.

Two separate concepts — don't confuse them:

- **Skin** — changes the CLI's appearance
- **Personality** — changes the agent's tone and wording

## Switch Skins

```bash
/skin                # Show current skin and list all available skins
/skin ares           # Switch to a built-in skin
/skin mytheme        # Switch to a custom skin from ~/.spark/skins/mytheme.yaml
```

To make a skin your permanent default, set it in `~/.spark/config.yaml`:

```yaml
display:
  skin: default
```

## Built-in Skins

| Skin | Description | Agent branding | Visual character |
|------|-------------|----------------|------------------|
| `default` | Classic Spark — gold and kawaii | `Spark Agent` | Warm gold borders, cornsilk text, kawaii faces in spinners. The familiar caduceus banner. Clean and inviting. |
| `ares` | War-god theme — crimson and bronze | `Ares Agent` | Deep crimson borders with bronze accents. Aggressive spinner verbs ("forging", "marching", "tempering steel"). Custom sword-and-shield ASCII art banner. |
| `mono` | Monochrome — clean grayscale | `Spark Agent` | All grays, no color. Borders are `#555555`, text is `#c9d1d9`. Ideal for minimal terminal setups or screen recordings. |
| `slate` | Cool blue — developer-focused | `Spark Agent` | Royal blue borders (`#4169e1`), soft blue text. Calm and professional. No custom spinner — uses default faces. |
| `daylight` | Light theme for bright terminals | `Spark Agent` | Designed for white or bright terminals. Dark slate text with blue borders, pale status surfaces, and a light completion menu that stays readable in light terminal profiles. |
| `warm-lightmode` | Warm brown/gold for light terminal backgrounds | `Spark Agent` | Warm parchment tones for light terminals. Dark brown text with saddle-brown accents, cream-colored status surfaces. An earthy alternative to the cooler daylight theme. |
| `poseidon` | Ocean-god theme — deep blue and seafoam | `Poseidon Agent` | Deep blue to seafoam gradient. Ocean-themed spinners ("charting currents", "sounding the depth"). Trident ASCII art banner. |
| `sisyphus` | Austere grayscale with persistence | `Sisyphus Agent` | Light grays with stark contrast. Boulder-themed spinners ("pushing uphill", "resetting the boulder", "enduring the loop"). Boulder-and-hill ASCII art banner. |
| `charizard` | Volcanic theme — burnt orange and ember | `Charizard Agent` | Warm burnt orange to ember gradient. Fire-themed spinners ("banking into the draft", "measuring burn"). Dragon-silhouette ASCII art banner. |

## All Configurable Keys

### Colors (`colors:`)

All color values are hex strings.

| Key | Description | Default (`default` skin) |
|-----|-------------|--------------------------|
| `banner_border` | Panel border around the startup banner | `#CD7F32` (bronze) |
| `banner_title` | Title text color in the banner | `#FFD700` (gold) |
| `banner_accent` | Section headers in the banner (Available Tools, etc.) | `#FFBF00` (amber) |
| `banner_dim` | Muted text in the banner (separators, secondary labels) | `#B8860B` (dark goldenrod) |
| `banner_text` | Body text in the banner (tool names, skill names) | `#FFF8DC` (cornsilk) |
| `ui_accent` | General UI accent color (highlights, active elements) | `#FFBF00` |
| `ui_label` | UI labels and tags | `#4dd0e1` (teal) |
| `ui_ok` | Success indicators (checkmarks, completion) | `#4caf50` (green) |
| `ui_error` | Error indicators (failures, blocked) | `#ef5350` (red) |
| `ui_warn` | Warning indicators (caution, approval prompts) | `#ffa726` (orange) |
| `prompt` | Interactive prompt text color | `#FFF8DC` |
| `input_rule` | Horizontal rule above the input area | `#CD7F32` |
| `response_border` | Border around the agent's response box (ANSI escape) | `#FFD700` |
| `session_label` | Session label color | `#DAA520` |
| `session_border` | Session ID dim border color | `#8B8682` |
| `status_bar_bg` | Background color for the TUI status / usage bar | `#1a1a2e` |
| `voice_status_bg` | Background color for the voice-mode status badge | `#1a1a2e` |
| `completion_menu_bg` | Background color for the completion menu list | `#1a1a2e` |
| `completion_menu_current_bg` | Background color for the active completion row | `#333355` |
| `completion_menu_meta_bg` | Background color for the completion meta column | `#1a1a2e` |
| `completion_menu_meta_current_bg` | Background color for the active completion meta column | `#333355` |

### Spinner (`spinner:`)

Controls the animated spinner shown while waiting for API responses.

| Key | Type | Description | Example |
|-----|------|-------------|---------|
| `waiting_faces` | list of strings | Faces cycled while waiting for API response | `["(*)", "(*)", "(^)"]` |
| `thinking_faces` | list of strings | Faces cycled during model reasoning | `["(*)", "(~)", "(<>)"]` |
| `thinking_verbs` | list of strings | Verbs shown in spinner messages | `["forging", "plotting", "hammering plans"]` |
| `wings` | list of [left, right] pairs | Decorative brackets around the spinner | `[["[*", "*]"], ["[^", "^]"]]` |

When spinner values are empty (as in `default` and `mono`), hardcoded defaults from `display.py` are used.

### Branding (`branding:`)

| Key | Description | Default |
|-----|-------------|---------|
| `agent_name` | Name shown in banner title and status display | `Spark Agent` |
| `welcome` | Welcome message shown at CLI startup | `Welcome to Spark Agent! Type your message or /help for commands.` |
| `goodbye` | Message shown on exit | `Goodbye!` |
| `response_label` | Label on the response box header | ` Spark ` |
| `prompt_symbol` | Symbol before the user input prompt | `> ` |
| `help_header` | Header text for the `/help` command output | `[?] Available Commands` |

### Other Top-Level Keys

| Key | Type | Description | Default |
|-----|------|-------------|---------|
| `tool_prefix` | string | Character prefixed to tool output lines in the CLI | `|` |
| `tool_emojis` | dict | Per-tool emoji overrides for spinners and progress (`{tool_name: emoji}`) | `{}` |
| `banner_logo` | string | Rich-markup ASCII art logo (replaces the default SPARK_AGENT banner) | `""` |
| `banner_hero` | string | Rich-markup hero art (replaces the default caduceus art) | `""` |

## Build a Custom Skin

Create YAML files under `~/.spark/skins/`. Your skin inherits missing values from the built-in `default` skin — you only need to specify what you want to change.

### Full skin template

```yaml
# ~/.spark/skins/mytheme.yaml
# Complete skin template — all keys shown. Delete any you don't need;
# missing values automatically inherit from the 'default' skin.

name: mytheme
description: My custom theme

colors:
  banner_border: "#CD7F32"
  banner_title: "#FFD700"
  banner_accent: "#FFBF00"
  banner_dim: "#B8860B"
  banner_text: "#FFF8DC"
  ui_accent: "#FFBF00"
  ui_label: "#4dd0e1"
  ui_ok: "#4caf50"
  ui_error: "#ef5350"
  ui_warn: "#ffa726"
  prompt: "#FFF8DC"
  input_rule: "#CD7F32"
  response_border: "#FFD700"
  session_label: "#DAA520"
  session_border: "#8B8682"
  status_bar_bg: "#1a1a2e"
  voice_status_bg: "#1a1a2e"
  completion_menu_bg: "#1a1a2e"
  completion_menu_current_bg: "#333355"
  completion_menu_meta_bg: "#1a1a2e"
  completion_menu_meta_current_bg: "#333355"

spinner:
  waiting_faces:
    - "(*)"
    - "(*)"
    - "(^)"
  thinking_faces:
    - "(*)"
    - "(~)"
    - "(<>)"
  thinking_verbs:
    - "processing"
    - "analyzing"
    - "computing"
    - "evaluating"
  wings:
    - ["[", "]"]
    - ["[*", "*]"]

branding:
  agent_name: "My Agent"
  welcome: "Welcome to My Agent! Type your message or /help for commands."
  goodbye: "See you later! "
  response_label: "  My Agent "
  prompt_symbol: " > "
  help_header: "() Available Commands"

tool_prefix: "|"

# Per-tool emoji overrides (optional)
tool_emojis:
  terminal: "*"
  web_search: "*"
  read_file: "*"

# Custom ASCII art banners (optional, Rich markup supported)
# banner_logo: |
#   [bold #FFD700] MY AGENT [/]
# banner_hero: |
#   [#FFD700]  Custom art here  [/]
```

### Minimal example

Since everything inherits from `default`, you only need to specify what's different:

```yaml
name: cyberpunk
description: Neon terminal theme

colors:
  banner_border: "#FF00FF"
  banner_title: "#00FFFF"
  banner_accent: "#FF1493"

spinner:
  thinking_verbs: ["jacking in", "decrypting", "uploading"]
  wings:
    - ["[", "]"]

branding:
  agent_name: "Cyber Agent"
  response_label: "  Cyber "

tool_prefix: ""
```

## Spark Mod — Visual Skin Editor

[Spark Mod](https://github.com/cocktailpeanut/spark-mod) is a community-built web UI for creating and managing skins visually. Point-and-click editing with live preview — no YAML required.

![Spark Mod skin editor](https://raw.githubusercontent.com/cocktailpeanut/spark-mod/master/nous.png)

**What it does:**

- Lists all built-in and custom skins
- Opens any skin in a visual editor with all Spark skin fields (colors, spinner, branding, tool prefix, tool emojis)
- Generates `banner_logo` text art from a text prompt
- Converts uploaded images (PNG, JPG, GIF, WEBP) into `banner_hero` ASCII art with multiple render styles (braille, ASCII ramp, blocks, dots)
- Saves directly to `~/.spark/skins/`
- Activates a skin by updating `~/.spark/config.yaml`
- Shows the generated YAML and a live preview

### Install Spark Mod

**Option 1 — Pinokio (1-click):**

Find it on [pinokio.computer](https://pinokio.computer) and install with one click.

**Option 2 — npx (quickest from terminal):**

```bash
npx -y spark-mod
```

**Option 3 — Manual:**

```bash
git clone https://github.com/cocktailpeanut/spark-mod.git
cd spark-mod/app
npm install
npm start
```

### Using Spark Mod

1. Start the app (via Pinokio or terminal)
2. Open **Skin Studio**
3. Choose a built-in or custom skin to edit
4. Generate a logo from text and/or upload an image for hero art — pick a render style and width
5. Edit colors, spinner, branding, and other fields
6. Click **Save** to write the skin YAML to `~/.spark/skins/`
7. Click **Activate** to set it as the current skin (updates `display.skin` in `config.yaml`)

Spark Mod respects the `SPARK_HOME` environment variable, so it works with [profiles](/docs/cli/profiles) too.

## Notes

- Built-in skins load from `spark_cli/skin_engine.py`
- Unknown skin names automatically fall back to `default`
- `/skin` updates the theme immediately for the current session only
- User skins in `~/.spark/skins/` take precedence over built-in skins with the same name
- To make a skin permanent, set it in `config.yaml` — `/skin` alone is session-only
- `banner_logo` and `banner_hero` support Rich console markup (e.g., `[bold #FF0000]text[/]`) for colored ASCII art
