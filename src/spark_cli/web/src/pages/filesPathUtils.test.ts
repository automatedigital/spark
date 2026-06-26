import { describe, expect, it } from "vitest";
import { fileEntryFromPath, parentDirForFile, ROOT_PATH, workspaceRelativePath } from "./filesPathUtils";

describe("files path utilities", () => {
  it.each([
    ["files/a.md", "files/a.md"],
    ["./files/a.md", "files/a.md"],
    ["reports/2026/summary.md", "reports/2026/summary.md"],
    ['"files/a.md"', "files/a.md"],
    ["`files/a.md`", "files/a.md"],
    ["files\\a.md", "files/a.md"],
    ["/Users/joe/.spark/workspace/files/a.md", "files/a.md"],
    ["/Users/joe/.spark/profiles/dev/workspace/files/a.md", "files/a.md"],
    ["~/.spark/workspace/files/a.md", "files/a.md"],
    ["~/.spark/profiles/dev/workspace/reports/2026/summary.md", "reports/2026/summary.md"],
  ])("normalizes %s to workspace-relative %s", (input, expected) => {
    expect(workspaceRelativePath(input)).toBe(expected);
  });

  it("rejects non-workspace absolute paths as workspace-relative paths", () => {
    expect(workspaceRelativePath("/Users/joe/Downloads/a.md")).toBeNull();
    expect(workspaceRelativePath("C:\\Users\\joe\\Downloads\\a.md")).toBeNull();
  });

  it("rejects traversal paths", () => {
    expect(workspaceRelativePath("../a.md")).toBeNull();
    expect(workspaceRelativePath("files/../a.md")).toBeNull();
    expect(workspaceRelativePath("/Users/joe/.spark/workspace/../a.md")).toBeNull();
  });

  it("finds the parent directory for selectable files", () => {
    expect(parentDirForFile("files/a.md")).toBe("files");
    expect(parentDirForFile("./reports/2026/summary.md")).toBe("reports/2026");
    expect(parentDirForFile("/Users/joe/.spark/profiles/dev/workspace/files/a.md")).toBe("files");
    expect(parentDirForFile("a.md")).toBe(ROOT_PATH);
    expect(parentDirForFile("/Users/joe/Downloads/a.md")).toBe(ROOT_PATH);
  });

  it("builds file entries from displayed paths", () => {
    expect(fileEntryFromPath("./files/a.md")).toEqual({
      name: "a.md",
      path: "files/a.md",
      type: "file",
    });
    expect(fileEntryFromPath("/Users/joe/.spark/workspace/reports/2026/summary.md")).toEqual({
      name: "summary.md",
      path: "reports/2026/summary.md",
      type: "file",
    });
    expect(fileEntryFromPath("/Users/joe/Downloads/a.md", '"Shown.md"')).toEqual({
      name: "Shown.md",
      path: "/Users/joe/Downloads/a.md",
      type: "file",
    });
  });
});
