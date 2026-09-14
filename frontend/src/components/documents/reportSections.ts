/**
 * A narrative report, split back into the sections it was written under.
 *
 * Report templates fill the entry box under capitalised headings --
 * FINDINGS, IMPRESSION, ADVICE -- and the printed report reads them back as
 * sections, so a report typed by hand under the same headings prints the same
 * way. Text with no headings is one untitled section: nothing is lost.
 */

export interface ReportSection {
  heading: string | null;
  body: string;
}

const HEADING = /^([A-Z][A-Z ]{2,30}):?$/;

export function reportSections(text: string): ReportSection[] {
  const sections: { heading: string | null; lines: string[] }[] = [];
  let current: { heading: string | null; lines: string[] } = { heading: null, lines: [] };

  for (const line of text.split(/\r?\n/)) {
    const match = HEADING.exec(line.trim());
    if (match) {
      sections.push(current);
      current = { heading: match[1].trim(), lines: [] };
    } else {
      current.lines.push(line);
    }
  }
  sections.push(current);

  return sections
    .map((section) => ({ heading: section.heading, body: section.lines.join("\n").trim() }))
    .filter((section) => section.heading || section.body);
}
