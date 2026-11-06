import { apiConnectionGeneration, fetchJSON } from "./apiHelpers";

export interface ProviderCatalogEntry {
  id: string;
  label: string;
  credential: { mechanism: string; env_vars: string[]; configured: boolean };
  base_url: { policy: "editable"; default: string };
  availability: "unknown";
  capabilities: Record<string, "supported" | "disabled" | "unknown">;
}

interface ProviderCatalog {
  schema_version: 1;
  providers: ProviderCatalogEntry[];
  selected_provider: string;
}

export async function getProviderCatalog(): Promise<ProviderCatalog> {
  const generation = apiConnectionGeneration();
  const result = await fetchJSON<ProviderCatalog>("/api/providers/catalogue", { cache: "no-store" });
  if (generation !== apiConnectionGeneration()) throw new Error("Provider catalogue connection changed");
  return result;
}
