import type { SettingDestination } from "@/lib/settingsRegistry";
let nextLabelId = 0;
const controls = 'input:not([type="hidden"]), textarea, select, button, [role="switch"], [role="combobox"]';

/** Associate existing rendered labels from outer field wrappers; no editor state changes. */
export function labelSettingControls(root: HTMLElement) {
  for (const label of root.querySelectorAll<HTMLLabelElement>("label")) {
    if (label.control) continue;
    let parent = label.parentElement;
    while (parent && parent !== root) {
      const candidates = [...parent.querySelectorAll<HTMLElement>(controls)].filter((control) => control.textContent?.trim() !== "Refresh");
      if (candidates.length) {
        const control = candidates[0];
        label.id ||= `${root.id}-label-${++nextLabelId}`;
        if (!control.hasAttribute("aria-label") && !control.hasAttribute("aria-labelledby")) control.setAttribute("aria-labelledby", label.id);
        break;
      }
      parent = parent.parentElement;
    }
  }
}
export function focusSetting(root: HTMLElement, destination: SettingDestination): boolean {
  const field = destination.fieldKey ? [...root.querySelectorAll<HTMLElement>("[data-setting-key]")].find((el) => el.dataset.settingKey === destination.fieldKey) : root;
  if (!field) return false;
  let target: HTMLElement | undefined;
  if (destination.controlLabel) {
    const label = [...field.querySelectorAll<HTMLLabelElement>("label")].find((el) => el.textContent?.trim() === destination.controlLabel);
    if (!label) return false;
    target = label.control ?? [...field.querySelectorAll<HTMLElement>(controls)].find((control) => control.getAttribute("aria-labelledby") === label.id);
  } else if (destination.fieldKey) target = field.querySelector<HTMLElement>(controls) ?? undefined;
  else if (!root.querySelector('[role="status"]') || root.querySelector("h2, h3, input, button")) target = root;
  if (!target) return false;
  for (let parent = target.parentElement; parent && parent !== root; parent = parent.parentElement) if (parent instanceof HTMLDetailsElement) parent.open = true;
  if (target === root) target.tabIndex = -1;
  target.scrollIntoView({ block: "nearest" });
  target.focus();
  return document.activeElement === target;
}
