import { useEffect, useMemo, useRef, useState } from "react";
import ReactCodeMirror, { keymap } from "@uiw/react-codemirror";
import type { Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";

type LanguageLoader = () => Promise<Extension>;

const languageLoaders: Record<string, LanguageLoader> = {
  py: () => import("@codemirror/lang-python").then(({ python }) => python()),
  js: () => import("@codemirror/lang-javascript").then(({ javascript }) => javascript({ jsx: true })),
  jsx: () => import("@codemirror/lang-javascript").then(({ javascript }) => javascript({ jsx: true })),
  ts: () => import("@codemirror/lang-javascript").then(({ javascript }) => javascript({ typescript: true })),
  tsx: () => import("@codemirror/lang-javascript").then(({ javascript }) => javascript({ typescript: true, jsx: true })),
  md: () => import("@codemirror/lang-markdown").then(({ markdown }) => markdown()),
  json: () => import("@codemirror/lang-json").then(({ json }) => json()),
  html: () => import("@codemirror/lang-html").then(({ html }) => html()),
  css: () => import("@codemirror/lang-css").then(({ css }) => css()),
  sql: () => import("@codemirror/lang-sql").then(({ sql }) => sql()),
  rs: () => import("@codemirror/lang-rust").then(({ rust }) => rust()),
  go: () => import("@codemirror/lang-go").then(({ go }) => go()),
  java: () => import("@codemirror/lang-java").then(({ java }) => java()),
  c: () => import("@codemirror/lang-cpp").then(({ cpp }) => cpp()),
  cpp: () => import("@codemirror/lang-cpp").then(({ cpp }) => cpp()),
  h: () => import("@codemirror/lang-cpp").then(({ cpp }) => cpp()),
  xml: () => import("@codemirror/lang-xml").then(({ xml }) => xml()),
  svg: () => import("@codemirror/lang-xml").then(({ xml }) => xml()),
  sh: async () => {
    const [{ StreamLanguage }, { shell }] = await Promise.all([
      import("@codemirror/language"),
      import("@codemirror/legacy-modes/mode/shell"),
    ]);
    return StreamLanguage.define(shell);
  },
  bash: async () => {
    const [{ StreamLanguage }, { shell }] = await Promise.all([
      import("@codemirror/language"),
      import("@codemirror/legacy-modes/mode/shell"),
    ]);
    return StreamLanguage.define(shell);
  },
  yaml: async () => {
    const [{ StreamLanguage }, { yaml }] = await Promise.all([
      import("@codemirror/language"),
      import("@codemirror/legacy-modes/mode/yaml"),
    ]);
    return StreamLanguage.define(yaml);
  },
  yml: async () => {
    const [{ StreamLanguage }, { yaml }] = await Promise.all([
      import("@codemirror/language"),
      import("@codemirror/legacy-modes/mode/yaml"),
    ]);
    return StreamLanguage.define(yaml);
  },
  toml: () => loadTomlMode(),
  ini: () => loadTomlMode(),
  cfg: () => loadTomlMode(),
  env: () => loadTomlMode(),
};

async function loadTomlMode(): Promise<Extension> {
  const [{ StreamLanguage }, { toml }] = await Promise.all([
    import("@codemirror/language"),
    import("@codemirror/legacy-modes/mode/toml"),
  ]);
  return StreamLanguage.define(toml);
}

function languageExtensionForFilename(filename: string): LanguageLoader | null {
  const extension = filename.split(".").pop()?.toLowerCase() ?? "";
  return languageLoaders[extension] ?? null;
}

const cmLayout = [
  EditorView.theme({
    "&": { height: "100%", fontSize: "0.72rem" },
    ".cm-scroller": { fontFamily: "var(--font-mono-ui, monospace)", lineHeight: "1.25rem", overflow: "auto" },
    ".cm-content": { padding: "0.75rem 0" },
    ".cm-line": { padding: "0 1rem" },
    ".cm-gutters": { minWidth: "2.5rem", borderRight: "1px solid rgba(255,255,255,0.06)" },
    ".cm-activeLine": { background: "rgba(255,255,255,0.03)" },
    ".cm-activeLineGutter": { background: "rgba(255,255,255,0.03)" },
  }),
  EditorView.theme({
    "&, &.cm-focused": { background: "transparent !important" },
    ".cm-editor, .cm-wrap": { background: "transparent !important" },
    ".cm-scroller": { background: "transparent !important" },
    ".cm-content": { background: "transparent !important" },
    ".cm-gutters": { background: "transparent !important" },
  }, { dark: true }),
];

export default function CodeEditor({
  filename,
  value,
  onChange,
  onSave,
}: {
  filename: string;
  value: string;
  onChange: (content: string) => void;
  onSave: () => void;
}) {
  const onSaveRef = useRef(onSave);
  const [languageExtension, setLanguageExtension] = useState<Extension | null>(null);
  onSaveRef.current = onSave;

  useEffect(() => {
    let cancelled = false;
    setLanguageExtension(null);
    const loader = languageExtensionForFilename(filename);
    if (loader) {
      void loader()
        .then((extension) => {
          if (!cancelled) setLanguageExtension(extension);
        })
        .catch((error) => {
          // Editing remains available as plain text if syntax support fails.
          console.error(`Failed to load CodeMirror language for ${filename}`, error);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [filename]);

  const extensions = useMemo(() => {
    const saveBinding = keymap.of([{
      key: "Mod-s",
      run: () => {
        onSaveRef.current();
        return true;
      },
    }]);
    return languageExtension
      ? [saveBinding, languageExtension, ...cmLayout]
      : [saveBinding, ...cmLayout];
  }, [languageExtension]);

  return (
    <ReactCodeMirror
      value={value}
      onChange={onChange}
      theme={oneDark}
      extensions={extensions}
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        dropCursor: false,
        allowMultipleSelections: true,
        indentOnInput: true,
        bracketMatching: true,
        closeBrackets: true,
        autocompletion: false,
        rectangularSelection: false,
        crosshairCursor: false,
        highlightActiveLine: true,
        highlightSelectionMatches: true,
        closeBracketsKeymap: false,
        searchKeymap: false,
        foldKeymap: false,
        completionKeymap: false,
        lintKeymap: false,
      }}
      style={{ height: "100%" }}
    />
  );
}
