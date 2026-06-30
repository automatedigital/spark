import type { ProjectTemplate } from "@/lib/api";

export function chooseDefaultStarter(starters: ProjectTemplate[]): ProjectTemplate | undefined {
  return (
    starters.find((starter) => starter.recommended && starter.available) ??
    starters.find((starter) => starter.available) ??
    starters[0]
  );
}

export function toggleProjectWizardValue(values: string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}
