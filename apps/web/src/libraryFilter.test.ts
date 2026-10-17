import { describe, expect, it } from "vitest";
import { filterDocs } from "./libraryFilter";

const docs = [{ filename: "Acme_CIM.pdf" }, { filename: "acme_10k.xlsx" }, { filename: "Beta_memo.docx" }];

describe("filterDocs", () => {
  it("keeps everything for an empty or blank query", () => {
    expect(filterDocs(docs, "")).toHaveLength(3);
    expect(filterDocs(docs, "   ")).toHaveLength(3);
  });
  it("matches any part of the filename, ignoring case", () => {
    expect(filterDocs(docs, "ACME").map((d) => d.filename)).toEqual(["Acme_CIM.pdf", "acme_10k.xlsx"]);
    expect(filterDocs(docs, "memo").map((d) => d.filename)).toEqual(["Beta_memo.docx"]);
  });
  it("returns nothing when no name matches", () => {
    expect(filterDocs(docs, "zeta")).toEqual([]);
  });
});
