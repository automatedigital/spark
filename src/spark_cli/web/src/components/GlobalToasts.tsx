import { useToast } from "@/hooks/useToast";
import { useEventBus } from "@/hooks/useEventBus";
import { Toast } from "@/components/Toast";

/**
 * App-wide transient toasts driven by the event bus. Currently surfaces
 * "memory updated" when the agent curates memory (incl. background reviews) —
 * there's no dedicated Memory page yet, so this is the surface for it.
 */
export function GlobalToasts() {
  const { toast, showToast } = useToast();

  useEventBus((env) => {
    if (env.topic === "memory.updated") {
      showToast("Memory updated", "success");
    }
  });

  return <Toast toast={toast} />;
}
