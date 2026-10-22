#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} = require("docx");

const root = path.resolve(__dirname, "..");
const source = path.join(root, "docs/weekly reports/week8-member1-contribution-report.md");
const destination = path.join(root, "docs/weekly reports/Week8_Member1_Contribution_Report.docx");

function runs(text) {
  const output = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) output.push(new TextRun({ text: text.slice(cursor, match.index), font: "Times New Roman", size: 24 }));
    const token = match[0];
    const isCode = token.startsWith("`");
    output.push(new TextRun({
      text: isCode ? token.slice(1, -1) : token.slice(2, -2),
      font: isCode ? "Courier New" : "Times New Roman",
      size: isCode ? 21 : 24,
      bold: !isCode,
    }));
    cursor = match.index + token.length;
  }
  if (cursor < text.length) output.push(new TextRun({ text: text.slice(cursor), font: "Times New Roman", size: 24 }));
  return output;
}

function paragraph(text, options = {}) {
  return new Paragraph({
    alignment: options.justify ? AlignmentType.JUSTIFIED : AlignmentType.LEFT,
    spacing: { after: 140, line: 276 },
    bullet: options.bullet ? { level: 0 } : undefined,
    children: runs(text),
  });
}

function table(rows) {
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: rows.map((row, index) => new TableRow({
      children: row.map((cell) => new TableCell({
        children: [new Paragraph({ children: [new TextRun({
          text: cell,
          font: "Times New Roman",
          size: 20,
          bold: index === 0,
        })] })],
      })),
    })),
  });
}

function convert(markdown) {
  const children = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  let rows = [];
  const flush = () => {
    if (rows.length) {
      children.push(table(rows));
      rows = [];
    }
  };
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flush();
    } else if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line.slice(1, -1).split("|").map((cell) => cell.trim());
      if (!cells.every((cell) => /^:?-{3,}:?$/.test(cell))) rows.push(cells);
    } else {
      flush();
      if (line.startsWith("# ")) children.push(new Paragraph({ text: line.slice(2), heading: HeadingLevel.HEADING_1 }));
      else if (line.startsWith("## ")) children.push(new Paragraph({ text: line.slice(3), heading: HeadingLevel.HEADING_2 }));
      else if (line.startsWith("- ")) children.push(paragraph(line.slice(2), { bullet: true }));
      else if (/^\d+\.\s/.test(line)) children.push(paragraph(line.replace(/^\d+\.\s/, ""), { bullet: true }));
      else children.push(paragraph(line, { justify: true }));
    }
  }
  flush();
  return children;
}

async function main() {
  const document = new Document({
    styles: { default: { document: { run: { font: "Times New Roman", size: 24 } } } },
    sections: [{ children: convert(fs.readFileSync(source, "utf8")) }],
  });
  fs.writeFileSync(destination, await Packer.toBuffer(document));
  console.log(`Created ${destination}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
