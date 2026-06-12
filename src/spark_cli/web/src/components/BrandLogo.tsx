import { useWebUITheme, type WebUITheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

// Themes with a light (bright) background. On these, the dark glyph
// (`icon_small-light.png`) reads; everywhere else the white/light glyph
// (`icon_small-dark.png`) is used.
const LIGHT_THEMES = new Set<WebUITheme>(["daylight"]);

// Asset names are inverted vs. intuition: `icon_small-dark.png` is the WHITE
// glyph (for dark backgrounds), `icon_small-light.png` is the dark glyph.
export function BrandLogo({ className }: { className?: string }) {
  const { theme } = useWebUITheme();
  const src = LIGHT_THEMES.has(theme) ? "/icon_small-light.png" : "/icon_small-dark.png";
  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      className={cn("block object-contain", className)}
      draggable={false}
    />
  );
}
