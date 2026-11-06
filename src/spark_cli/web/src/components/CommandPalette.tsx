import { PAGE_DESTINATIONS, SETTINGS_SECTIONS } from "@/lib/settingsRegistry";
import { useEffect, useMemo, useRef, useState } from "react";
import { Search, MessageSquare, MessageCircle, Clock, Package, Plug, Settings, FolderOpen, Loader2, Brain, Blocks } from "lucide-react";
import { cachedPaletteRecent, paletteCategories, paletteItemKey, paletteScope, readPalette, type PaletteCategory, type PaletteItem, type PalettePage } from "@/lib/paletteClient";
import { SIDEBAR_SCOPE_EVENT, sidebarPreferenceScopeReady } from "@/lib/sidebarPrefs";
