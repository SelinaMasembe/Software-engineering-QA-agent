#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  TextRun,
} = require("docx");

const root = path.resolve(__dirname, "..");
const source = path.join(root, "docs/evaluation/final-report-sections-1-2.md");
const destination = path.join(root, "docs/evaluation/Final_Report_Sections_1_and_2.docx");

function inlineRuns(text) {
  const result = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) {
      result.push(new TextRun({
        text: text.slice(cursor, match.index),
        font: "Times New Roman",
        size: 24,
      }));
    }
    const token = match[0];
    const code = token.startsWith("`");
    result.push(new TextRun({
      text: code ? token.slice(1, -1) : token.slice(2, -2),
      font: code ? "Courier New" : "Times New Roman",
      size: code ? 21 : 24,
      bold: !code,
    }));
    cursor = match.index + token.length;
  }
  if (cursor < text.length) {
    result.push(new TextRun({
      text: text.slice(cursor),
      font: "Times New Roman",
      size: 24,
    }));
  }
  return result;
}

function body(text, bullet = false) {
  return new Paragraph({
    alignment: AlignmentType.JUSTIFIED,
    spacing: { after: 140, line: 276 },
    indent: bullet ? { left: 360, hanging: 180 } : undefined,
    bullet: bullet ? { level: 0 } : undefined,
    children: inlineRuns(text),
  });
}

function heading(text, level) {
  return new Paragraph({
    text,
    heading: level === 1 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2,
    keepNext: true,
    spacing: { before: 240, after: 120 },
  });
}

function parseMarkdown(markdown) {
  const children = [];
  const blocks = markdown.replace(/\r\n/g, "\n").split(/\n\s*\n/);
  for (const rawBlock of blocks) {
    const lines = rawBlock.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!lines.length) continue;
    const first = lines[0];
    if (first.startsWith("# ")) {
      children.push(heading(first.slice(2), 1));
    } else if (first.startsWith("## ")) {
      children.push(heading(first.slice(3), 2));
    } else if (first.startsWith("### ")) {
      children.push(heading(first.slice(4), 2));
    } else if (lines.every((line) => line.startsWith("- "))) {
      for (const line of lines) children.push(body(line.slice(2), true));
    } else if (lines.every((line) => /^\d+\.\s/.test(line))) {
      for (const line of lines) children.push(body(line.replace(/^\d+\.\s/, ""), true));
    } else {
      children.push(body(lines.join(" ")));
    }
  }
  return children;
}

async function main() {
  const document = new Document({
    styles: {
      default: {
        document: {
          run: { font: "Times New Roman", size: 24 },
        },
      },
    },
    sections: [{
      page: {
        width: 11907,
        height: 16838,
        margin: { top: 720, right: 720, bottom: 720, left: 720 },
      },
      children: parseMarkdown(fs.readFileSync(source, "utf8")),
    }],
  });
  fs.writeFileSync(destination, await Packer.toBuffer(document));
  console.log(`Created ${destination}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
