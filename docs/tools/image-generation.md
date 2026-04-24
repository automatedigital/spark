---
title: Image Generation
description: Generate high-quality images using FLUX 2 Pro with automatic upscaling via FAL.ai.
sidebar_label: Image Generation
sidebar_position: 6
---

# Image Generation

Ask Spark to generate an image and it creates one using **FLUX 2 Pro** via FAL.ai, then automatically upscales it 2x with the **Clarity Upscaler** for sharper results.

---

## Setup

### 1. Get a FAL API Key

Sign up at [fal.ai](https://fal.ai/) and generate an API key from your dashboard.

### 2. Add the Key

```bash
# Add to ~/.spark/.env
FAL_KEY=your-fal-api-key-here
```

### 3. Install the Client Library

```bash
pip install fal-client
```

:::info
The image generation tool activates automatically when `FAL_KEY` is set. No extra toolset configuration needed.
:::

---

## Generate an Image

Just describe what you want:

```
Generate an image of a serene mountain landscape with cherry blossoms
```

```
Create a portrait of a wise old owl perched on an ancient tree branch
```

```
Make me a futuristic cityscape with flying cars and neon lights
```

---

## What Happens Behind the Scenes

1. **Generation** — Your prompt goes to the FLUX 2 Pro model (`fal-ai/flux-2-pro`)
2. **Upscaling** — The result is upscaled 2x via the Clarity Upscaler (`fal-ai/clarity-upscaler`)
3. **Delivery** — The upscaled image URL comes back to you

If the upscaler fails for any reason (network issue, rate limit), the original image is returned as a fallback.

---

## Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `prompt` | *(required)* | — | Text description of the desired image |
| `aspect_ratio` | `"landscape"` | `landscape`, `square`, `portrait` | Image aspect ratio |
| `num_inference_steps` | `50` | 1–100 | Denoising steps — more steps = higher quality, slower generation |
| `guidance_scale` | `4.5` | 0.1–20.0 | How closely to follow the prompt |
| `num_images` | `1` | 1–4 | Number of images to generate |
| `output_format` | `"png"` | `png`, `jpeg` | Image file format |
| `seed` | *(random)* | any integer | Fix a seed for reproducible results |

---

## Aspect Ratios

| Aspect Ratio | Maps To | Best For |
|-------------|---------|----------|
| `landscape` | `landscape_16_9` | Wallpapers, banners, scenes |
| `square` | `square_hd` | Profile pictures, social media posts |
| `portrait` | `portrait_16_9` | Character art, phone wallpapers |

:::tip
You can also use FLUX 2 Pro size presets directly: `square_hd`, `square`, `portrait_4_3`, `portrait_16_9`, `landscape_4_3`, `landscape_16_9`. Custom sizes up to 2048×2048 are also supported.
:::

---

## Automatic Upscaling

Every generated image is automatically upscaled 2x with these Clarity Upscaler settings:

| Setting | Value |
|---------|-------|
| Upscale Factor | 2x |
| Creativity | 0.35 |
| Resemblance | 0.6 |
| Guidance Scale | 4 |
| Inference Steps | 18 |
| Positive Prompt | `"masterpiece, best quality, highres"` + your original prompt |
| Negative Prompt | `"(worst quality, low quality, normal quality:2)"` |

The upscaler enhances detail and resolution while keeping the original composition intact.

---

## Example Prompts

```
A candid street photo of a woman with a pink bob and bold eyeliner
```

```
Modern architecture building with glass facade, sunset lighting
```

```
Abstract art with vibrant colors and geometric patterns
```

```
Portrait of a wise old owl perched on ancient tree branch
```

```
Futuristic cityscape with flying cars and neon lights
```

---

## How Images Are Delivered

The delivery method varies by platform:

| Platform | Delivery method |
|----------|----------------|
| **CLI** | Image URL printed as markdown `![description](url)` — click to open in browser |
| **Telegram** | Photo message with the prompt as caption |
| **Discord** | Image embedded in a message |
| **Slack** | Image URL in message (Slack unfurls it) |
| **WhatsApp** | Image sent as a media message |
| **Other platforms** | Image URL in plain text |

The agent uses `MEDIA:<url>` syntax in its response, which each platform adapter converts to the appropriate format.

---

## Debug Logging

```bash
export IMAGE_TOOLS_DEBUG=true
```

Debug logs are saved to `./logs/image_tools_debug_<session_id>.json` with details on each generation request, parameters, timing, and errors.

---

## Safety Settings

The image generation tool runs with safety checks disabled by default (`safety_tolerance: 5`, the most permissive setting). This is configured at the code level and is not user-adjustable.

---

## Limitations

- **FAL API key required** — image generation incurs costs on your FAL.ai account
- **Text-to-image only** — no inpainting or img2img
- **URL-based delivery** — images are returned as temporary FAL.ai URLs, not saved locally; URLs typically expire after a few hours
- **Upscaling adds latency** — the 2x upscale step adds processing time
- **Max 4 images per request** — `num_images` is capped at 4
