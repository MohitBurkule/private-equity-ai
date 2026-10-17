// Case-insensitive match on filename, so a reviewer can find a document by any part of its name. An empty
// query keeps every document: the filter narrows the list, it never hides documents by default.
export function filterDocs<T extends { filename: string }>(docs: T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  return q ? docs.filter((d) => d.filename.toLowerCase().includes(q)) : docs;
}
