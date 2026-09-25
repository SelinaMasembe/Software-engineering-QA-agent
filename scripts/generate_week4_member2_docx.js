#!/usr/bin/env node

/** Generate the formal Week 4 Member 2 deliverable as a Word document. */

const fs = require("fs");
const path = require("path");
const JSZip = require("jszip");
const {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  ImageRun,
  LevelFormat,
  Packer,
  PageBreak,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} = require("docx");

const REPO_ROOT = path.resolve(__dirname, "..");
const REFERENCE_DOCX = path.join(
  REPO_ROOT,
  "docs/integration/Week3_Member2_RetrievalPipeline.docx",
);
const ARCHITECTURE_PNG = path.join(
  REPO_ROOT,
  "docs/architecture/l4-tool-calling.png",
);
const OUTPUT_DOCX = path.join(
  REPO_ROOT,
  "docs/integration/Week4_Member2_ToolCallingOrchestration.docx",
);

const A4_WIDTH = 11907;
const A4_HEIGHT = 16838;
const PAGE_MARGIN = 1080;
const CONTENT_WIDTH = A4_WIDTH - 2 * PAGE_MARGIN;
const FONT = "Times New Roman";
const CODE_FONT = "Courier New";

const thinBorders = {
  top: { style: BorderStyle.SINGLE, size: 4, color: "808080" },
  bottom: { style: BorderStyle.SINGLE, size: 4, color: "808080" },
  left: { style: BorderStyle.SINGLE, size: 4, color: "808080" },
  right: { style: BorderStyle.SINGLE, size: 4, color: "808080" },
  insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
  insideVertical: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
};

const noBorders = {
  top: { style: BorderStyle.NIL, size: 0, color: "FFFFFF" },
  bottom: { style: BorderStyle.NIL, size: 0, color: "FFFFFF" },
  left: { style: BorderStyle.NIL, size: 0, color: "FFFFFF" },
  right: { style: BorderStyle.NIL, size: 0, color: "FFFFFF" },
  insideHorizontal: { style: BorderStyle.NIL, size: 0, color: "FFFFFF" },
  insideVertical: { style: BorderStyle.NIL, size: 0, color: "FFFFFF" },
};

function run(text, options = {}) {
  return new TextRun({
    text,
    font: options.font || FONT,
    size: options.size || 24,
    bold: options.bold,
    italics: options.italics,
    color: options.color,
  });
}

function body(text, options = {}) {
  return new Paragraph({
    alignment: options.alignment || AlignmentType.JUSTIFIED,
    spacing: {
      after: options.after === undefined ? 120 : options.after,
      line: options.line || 276,
    },
    indent: options.indent,
    keepNext: options.keepNext,
    children: Array.isArray(text) ? text : [run(text, options)],
  });
}

function heading(text, level = 1) {
  return new Paragraph({
    text,
    heading: level === 1 ? "Heading1" : "Heading2",
    keepNext: true,
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "report-bullets", level: 0 },
    spacing: { after: 80, line: 276 },
    children: [run(text)],
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function caption(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 160 },
    keepNext: true,
    children: [run(text, { size: 18, italics: true })],
  });
}

function makeCell(content, width, options = {}) {
  const paragraphs = Array.isArray(content) ? content : [content];
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    verticalAlign: options.verticalAlign || VerticalAlign.CENTER,
    shading: options.fill
      ? { fill: options.fill, type: ShadingType.CLEAR, color: "auto" }
      : undefined,
    margins: { top: 70, bottom: 70, left: 90, right: 90 },
    children: paragraphs.map((item) => {
      if (item instanceof Paragraph) return item;
      return new Paragraph({
        spacing: { after: 0, line: 240 },
        alignment: options.alignment || AlignmentType.LEFT,
        children: [
          run(String(item), {
            size: options.size || 20,
            bold: options.bold,
            italics: options.italics,
          }),
        ],
      });
    }),
  });
}

function makeTable(headers, rows, widths, options = {}) {
  if (widths.reduce((sum, width) => sum + width, 0) !== CONTENT_WIDTH) {
    throw new Error("Table column widths must equal the content width.");
  }
  const tableRows = [];
  if (headers) {
    tableRows.push(
      new TableRow({
        cantSplit: true,
        tableHeader: true,
        children: headers.map((header, index) =>
          makeCell(header, widths[index], {
            fill: "D9E1F2",
            bold: true,
            alignment: AlignmentType.CENTER,
          }),
        ),
      }),
    );
  }
  for (const row of rows) {
    tableRows.push(
      new TableRow({
        cantSplit: true,
        children: row.map((value, index) =>
          makeCell(value, widths[index], {
            fill: options.alternate && tableRows.length % 2 === 0 ? "F7F7F7" : undefined,
          }),
        ),
      }),
    );
  }
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    layout: TableLayoutType.FIXED,
    borders: thinBorders,
    rows: tableRows,
  });
}

function codeBlock(lines) {
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    layout: TableLayoutType.FIXED,
    borders: noBorders,
    rows: [
      new TableRow({
        cantSplit: true,
        children: [
          new TableCell({
            width: { size: CONTENT_WIDTH, type: WidthType.DXA },
            shading: { fill: "F2F2F2", type: ShadingType.CLEAR, color: "auto" },
            margins: { top: 90, bottom: 90, left: 130, right: 130 },
            children: lines.map(
              (line) =>
                new Paragraph({
                  spacing: { after: 0, line: 210 },
                  children: [run(line || " ", { font: CODE_FONT, size: 17 })],
                }),
            ),
          }),
        ],
      }),
    ],
  });
}

function tocLine(title, page, level = 0) {
  const available = level === 0 ? 75 : 69;
  const label = level === 0 ? title : `    ${title}`;
  const dots = ".".repeat(Math.max(5, available - label.length - String(page).length));
  return new Paragraph({
    spacing: { after: 90, line: 240 },
    indent: level ? { left: 360 } : undefined,
    children: [run(`${label} ${dots} ${page}`, { size: 22, bold: level === 0 })],
  });
}

async function extractLetterhead() {
  const archive = await JSZip.loadAsync(fs.readFileSync(REFERENCE_DOCX));
  const entry = archive.file("word/media/image1.png");
  if (!entry) throw new Error("Reference letterhead image was not found.");
  return entry.async("nodebuffer");
}

async function main() {
  const [letterhead, architecture] = await Promise.all([
    extractLetterhead(),
    fs.promises.readFile(ARCHITECTURE_PNG),
  ]);

  const children = [];

  // Page 1: cover.
  children.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 260 },
      children: [
        new ImageRun({
          data: letterhead,
          type: "png",
          transformation: { width: 624, height: 114 },
          altText: {
            title: "Makerere University letterhead",
            description: "Makerere University official letterhead used by the reference report.",
            name: "Makerere University letterhead",
          },
        }),
      ],
    }),
    body("COLLEGE OF COMPUTING AND INFORMATION SCIENCES", {
      alignment: AlignmentType.CENTER,
      bold: true,
      after: 50,
    }),
    body("SCHOOL OF COMPUTING AND INFORMATICS TECHNOLOGY", {
      alignment: AlignmentType.CENTER,
      bold: true,
      after: 50,
    }),
    body("DEPARTMENT OF NETWORKS", {
      alignment: AlignmentType.CENTER,
      bold: true,
      after: 190,
    }),
    body("BSE4104 EMERGING TRENDS IN SOFTWARE ENGINEERING", {
      alignment: AlignmentType.CENTER,
      bold: true,
      after: 50,
    }),
    body("AI-NATIVE & AGENTIC ENGINEERING CAPSTONE", {
      alignment: AlignmentType.CENTER,
      bold: true,
      after: 250,
    }),
    body("TOOL-CALLING ORCHESTRATION AND ARCHITECTURE UPDATE", {
      alignment: AlignmentType.CENTER,
      bold: true,
      size: 28,
      after: 60,
    }),
    body("OF THE SOFTWARE-ENGINEERING QA AGENT", {
      alignment: AlignmentType.CENTER,
      bold: true,
      size: 28,
      after: 150,
    }),
    body("WEEK 4 — MEMBER 2 DELIVERABLE", {
      alignment: AlignmentType.CENTER,
      bold: true,
      after: 160,
    }),
    body("GROUP J", {
      alignment: AlignmentType.CENTER,
      bold: true,
      after: 150,
    }),
    makeTable(
      ["NAME", "REGISTRATION NUMBER", "STUDENT NUMBER"],
      [
        ["Karagwa Ann Treasure", "2300709034", "23/U/09034/PS"],
        ["Ayan Mustafa Abdirahman", "2300722948", "23/X/22948/EVE"],
        ["Wanyana Selina Masembe", "2300701529", "23/U/1529"],
        ["Amabe Junior Humphrey", "2300705942", "23/U/05942/PS"],
        ["Akanga Andrew", "2300705555", "23/U/05555/PS"],
      ],
      [3449, 2700, 3598],
    ),
    pageBreak(),
  );

  // Page 2: contents.
  children.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 280 },
      children: [run("CONTENTS", { bold: true, size: 28 })],
    }),
    tocLine("1 Purpose and Deliverable", 3),
    tocLine("2 Scope of Work", 3),
    tocLine("3 Tool-Calling Flow", 4),
    tocLine("4 Design Decisions", 5),
    tocLine("4.1 Fixed Registry and Single-Turn Scope", 5, 1),
    tocLine("4.2 Fail-Closed Authorization and Approval", 5, 1),
    tocLine("4.3 Validation and Safe Result Boundaries", 5, 1),
    tocLine("5 Files Implemented", 6),
    tocLine("6 Interface Contracts and Handoffs", 7),
    tocLine("7 Verification", 8),
    tocLine("8 Architecture Changes Recorded", 9),
    tocLine("9 Evidence and Limitations", 9),
    tocLine("10 Open Items for the Team", 9),
    pageBreak(),
  );

  // Page 3: purpose and scope.
  children.push(
    heading("1 Purpose and Deliverable"),
    body(
      "This report records Member 2's Week 4 contribution to the Software-Engineering QA Agent. The deliverable is a safe, single-turn orchestration boundary that receives one structured model proposal, performs ordered checks, invokes at most one registered tool, and returns one stable, JSON-ready DispatchResult. The contribution also includes focused tests, a deterministic offline demonstration, and the L4 tool-calling architecture view.",
    ),
    body(
      "The implementation does not provide the production tools, define the human approval policy, authenticate the caller, or implement the Week 5 agent loop. Those boundaries remain explicit so that each team member can integrate through a small public contract without duplicating another member's contribution.",
    ),
    heading("2 Scope of Work"),
    makeTable(
      ["Work item", "Owner", "Integration boundary"],
      [
        ["Dispatcher, registry, results, statuses and codes", "Member 2", "Implemented in src/orchestration/."],
        ["ProposalSet, Action and structural parsing", "Member 1", "Reused through the shared model types."],
        ["Citation validation", "Member 1", "Caller must validate before dispatch()."],
        ["Four tools, schemas and role metadata", "Member 3", "Injected through the Tool protocol."],
        ["Failure and authorization evidence suite", "Member 4", "Runs against the integrated real tools."],
        ["Approval policy and human gate", "Member 5", "Injected through the ApprovalGate protocol."],
        ["Week 4 progress report", "Member 5", "Receives Member 2's evidence and architecture."],
      ],
      [2540, 1420, 5787],
      { alternate: true },
    ),
    caption("Table 1: Week 4 ownership and integration boundaries."),
    pageBreak(),
  );

  // Page 4: architecture.
  children.push(
    heading("3 Tool-Calling Flow"),
    body(
      "Figure 1 shows the application-layer path from a raw model response to a validated result. Solid blue outlines identify Member 2 components. Dashed outlines identify dependencies owned by Members 1, 3 and 5. Planned Member 3 tool modules shown in the diagram are integration targets and are not claimed as implemented by Member 2.",
    ),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 80, after: 80 },
      children: [
        new ImageRun({
          data: architecture,
          type: "png",
          transformation: { width: 650, height: 527 },
          altText: {
            title: "L4 tool-calling architecture",
            description: "Single-turn parsing, validation, authorization, approval and tool-dispatch flow.",
            name: "L4 tool-calling architecture",
          },
        }),
      ],
    }),
    caption(
      "Figure 1: L4 tool-calling architecture — solid outlines are Member 2; dashed outlines are integration dependencies.",
    ),
    body(
      "The production path is parse → citation validation → dispatch. The convenience method dispatch_raw() combines parsing and dispatch for isolated tests and the offline demonstration; it must not be used to bypass the citation-validation handoff.",
      { after: 0 },
    ),
    pageBreak(),
  );

  // Page 5: design decisions.
  children.push(
    heading("4 Design Decisions"),
    heading("4.1 Fixed Registry and Single-Turn Scope", 2),
    body(
      "ToolRegistry is a code-defined allow-list. Model output cannot add, rename or dynamically import a tool. One dispatch call handles one ProposalSet and returns; it does not plan another action or continue an autonomous loop.",
    ),
    heading("4.2 Fail-Closed Authorization and Approval", 2),
    body(
      "The dispatcher checks the caller-supplied ExecutionContext.role against the concrete tool's declared allowed_roles before validating arguments or executing. This is an authorization check, not authentication. Approval is requested only for tools marked REQUIRES_APPROVAL. A missing gate, gate exception, malformed verdict, denial or pending decision results in non-execution. The current boundary does not impose a timeout on a hanging gate or tool.",
    ),
    heading("4.3 Validation and Safe Result Boundaries", 2),
    body(
      "The concrete tool owns argument and output-schema validation. Member 2 additionally requires a mapping result, strict JSON serialization and a maximum encoded output size of 64,000 bytes by default. Arguments and outputs are deep-copied across boundaries. Exception text is excluded from result messages; the retained ProposalSet is also excluded from DispatchResult.to_dict().",
    ),
    heading("4.4 Stable Outcomes", 2),
    body(
      "Every non-successful path uses a stable DispatchStatus and, where applicable, a machine-readable DispatchCode. A valid tool action that is absent from the registry produces unknown_tool. An action outside the shared Action enum fails structural parsing and produces malformed_request.",
    ),
    makeTable(
      ["Status", "Representative codes", "Execution"],
      [
        ["executed", "none", "Tool ran once; output passed checks."],
        ["not_a_tool", "none", "Proposal required no tool."],
        ["rejected", "malformed_request, unknown_tool, unauthorized, invalid_arguments", "Tool did not run."],
        ["rejected", "approval_gate_missing, approval_unavailable, approval_denied", "Approval-required tool did not run."],
        ["awaiting_approval", "approval_pending", "Tool did not run."],
        ["tool_error", "execution_failed, invalid_output", "No validated output was returned."],
      ],
      [1900, 4350, 3497],
      { alternate: true },
    ),
    caption("Table 2: Stable dispatcher outcomes."),
    pageBreak(),
  );

  // Page 6: implemented files.
  children.push(
    heading("5 Files Implemented"),
    makeTable(
      ["File", "Purpose"],
      [
        ["src/orchestration/tool_dispatcher.py", "Implements the fixed registry, execution context, protocols, ordered safety checks and structured results."],
        ["src/orchestration/__init__.py", "Re-exports the public orchestration contracts for stable imports."],
        ["src/models/__init__.py", "Removes a circular package re-export so fresh RAG pipeline imports succeed."],
        ["tests/integration/test_tool_dispatcher.py", "Contains 16 offline tests for registry, authorization, approval, execution and output boundaries."],
        ["scripts/member2_tool_dispatch_demo.py", "Runs four deterministic scenarios with clearly labelled canned adapters."],
        ["docs/architecture/qa-agent-architecture (1).drawio", "Adds the editable fifth page, L4 · Tool calling."],
        ["docs/architecture/l4-tool-calling.png", "Provides the verified image embedded as Figure 1."],
        ["docs/ai-assistance credit/week4/member2-tool-calling.md", "Records AI assistance, accepted decisions and verification responsibility."],
      ],
      [3650, 6097],
      { alternate: true },
    ),
    caption("Table 3: Member 2 implementation and evidence files."),
    heading("5.1 Demonstration Boundary", 2),
    body(
      "DemoSearchRepoTool, DemoRunTestsTool and DemoApprovingGate are demonstration adapters only. They return canned data, execute no tests, read no repository files and implement no real approval policy. They must not be registered in the production application.",
    ),
    heading("5.2 Import Repair", 2),
    body(
      "The package-level model re-export created a circular import when rag.pipeline was imported in a fresh process. The re-export was removed while direct imports from models.client and models.types remain available. This repair is recorded separately from the dispatcher implementation in commit 6209aa3.",
      { after: 0 },
    ),
    pageBreak(),
  );

  // Page 7: contracts and handoffs.
  children.push(
    heading("6 Interface Contracts and Handoffs"),
    heading("6.1 Tool Contract — Member 3", 2),
    body(
      "Each concrete tool declares its action name, risk level and allowed roles, and owns its argument and output schemas. The dispatcher owns the order of checks and guarantees at most one run invocation.",
    ),
    codeBlock([
      "class Tool(Protocol):",
      "    name: str",
      "    risk: ToolRisk",
      "    allowed_roles: Collection[str]",
      "    def validate_arguments(self, arguments) -> dict: ...",
      "    def run(self, arguments, context) -> Mapping: ...",
      "    def validate_output(self, output) -> dict: ...",
    ]),
    heading("6.2 Approval Gate Contract — Member 5", 2),
    body(
      "The gate is called only for REQUIRES_APPROVAL tools and only after role and argument checks. It returns APPROVED, DENIED or PENDING. No missing or invalid decision can cause execution.",
    ),
    codeBlock([
      "class ApprovalGate(Protocol):",
      "    def check(",
      "        self, *, action: Action, arguments: Mapping,",
      "        context: ExecutionContext",
      "    ) -> ApprovalVerdict: ...",
    ]),
    heading("6.3 Citation and Test Handoffs", 2),
    body(
      "Member 1's caller validates proposal citations before dispatch(). Member 4 can exercise the same public boundary with Member 3's real tools to build the broader failure and authorization evidence matrix. Member 5 incorporates the resulting evidence into the team progress report.",
    ),
    makeTable(
      ["Handoff", "Owner", "Expected integration"],
      [
        ["Citation validation", "Member 1", "Parse, validate cited sources, then call dispatch()."],
        ["Production tool adapters", "Member 3", "Register implementations through the Tool protocol."],
        ["Integrated negative tests", "Member 4", "Exercise the dispatcher with the real tools."],
        ["Approval and reporting", "Member 5", "Supply ApprovalGate and record team evidence."],
      ],
      [2420, 1300, 6027],
      { alternate: true },
    ),
    caption("Table 4: Integration handoffs from the Member 2 boundary."),
    pageBreak(),
  );

  // Page 8: verification.
  children.push(
    heading("7 Verification"),
    body(
      "The focused Member 2 suite completed 16 offline tests successfully. The tests use FakeTool and FakeGate stand-ins and therefore verify the dispatcher boundary rather than Member 3's production tools or Member 4's integrated failure matrix.",
    ),
    makeTable(
      ["Verification area", "Evidence"],
      [
        ["Registry and action handling", "Allow-listed execution; duplicate, unsafe, unknown and non-tool handling."],
        ["Authorization and approval", "Role rejection; missing, denied, pending, failing and malformed gate outcomes."],
        ["Execution and output", "Exactly-once run; safe tool errors; mapping, schema, JSON and size enforcement."],
        ["Isolation", "Deep-copy boundaries and detached JSON-ready results."],
      ],
      [3200, 6547],
      { alternate: true },
    ),
    caption("Table 5: Focused dispatcher test coverage."),
    makeTable(
      ["Offline demo scenario", "Recorded result"],
      [
        ["read_only_search_executes", "executed"],
        ["run_tests_without_gate_rejected", "rejected / approval_gate_missing"],
        ["run_tests_with_approving_gate_executes", "executed with a canned approving gate"],
        ["unknown_action_rejected", "rejected / malformed_request"],
      ],
      [5200, 4547],
      { alternate: true },
    ),
    caption("Table 6: Four deterministic offline demonstration scenarios."),
    codeBlock([
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover \\",
      "  -s tests/integration -p \"test_tool_dispatcher.py\" -v",
      "PYTHONDONTWRITEBYTECODE=1 python3 scripts/member2_tool_dispatch_demo.py",
    ]),
    heading("7.1 Known Baseline Failure", 2),
    body(
      "The repository-wide suite is not claimed as fully passing. The original test-run log was replaced with a sanitized synthetic .txt fixture because the Week 3 sensitive-data guard blocks committed .log files. The RAG evaluation references and provenance metadata must point to the sanitized fixture consistently. Any remaining failures in this area are fixture-maintenance issues outside the Week 4 Member 2 dispatcher boundary.",
      { after: 0 },
    ),
    pageBreak(),
  );

  // Page 9: recorded architecture, evidence and team actions.
  children.push(
    heading("8 Architecture Changes Recorded"),
    body(
      "The editable Draw.io source now contains five pages. The added L4 page records the parser and citation-validation handoff, the fixed registry, role and schema checks, the conditional approval gate, exactly-once execution, strict output checks, and the structured DispatchResult returned to the application.",
    ),
    heading("9 Evidence and Limitations"),
    bullet("Incremental commits separate the import repair, dispatcher, tests, demo, architecture and documentation."),
    bullet("The L4 XML was parsed, the PNG was exported and visually inspected, and the focused tests and demo were run offline."),
    bullet("No performance claim is made; latency_ms is measured but deliberately normalized in demo output."),
    bullet("The dispatcher does not authenticate callers, time out dependencies, implement tools, or make human approval decisions."),
    bullet("AI assistance and the reviewed decisions are disclosed in docs/ai-assistance credit/week4/member2-tool-calling.md; responsibility for the submitted work remains with Member 2."),
    heading("10 Open Items for the Team"),
    bullet("Member 3: implement and register the four real tools and their schemas, risks and allowed roles."),
    bullet("Member 3: confirm that search_repo adapts RetrievalResult.to_search_repo_output()."),
    bullet("Member 5: implement ApprovalGate.check without timeout auto-approval."),
    bullet("Member 1: confirm citation validation occurs before dispatch()."),
    bullet("Member 4: run the integrated failure and authorization matrix against the real tools."),
    bullet("Member 5: include the test, demo and architecture evidence in the Week 4 progress report."),
    heading("10.1 Member 2 Commit Record", 2),
    body(
      "6209aa3 Import repair · 658d3e8 Dispatcher · 93f9fb3 Tests · 3462003 Demo · 718efef Architecture · 335f36d Contribution guide · 13e8a64 Validation ownership clarification.",
      { after: 0 },
    ),
  );

  const document = new Document({
    title: "Week 4 Member 2 Tool-Calling Orchestration",
    subject: "BSE4104 AI-Native and Agentic Engineering Capstone",
    creator: "Akanga Andrew",
    description:
      "Formal Week 4 Member 2 deliverable for tool-calling orchestration and architecture.",
    keywords: "BSE4104, tool calling, orchestration, QA agent, Group J",
    styles: {
      default: {
        document: {
          run: { font: FONT, size: 24, color: "000000" },
          paragraph: {
            alignment: AlignmentType.JUSTIFIED,
            spacing: { after: 160, line: 276 },
          },
        },
      },
      paragraphStyles: [
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { font: FONT, size: 24, bold: true },
          paragraph: {
            alignment: AlignmentType.JUSTIFIED,
            spacing: { before: 80, after: 120, line: 276 },
            keepNext: true,
            outlineLevel: 0,
          },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { font: FONT, size: 24, bold: true },
          paragraph: {
            alignment: AlignmentType.JUSTIFIED,
            spacing: { before: 60, after: 90, line: 276 },
            keepNext: true,
            outlineLevel: 1,
          },
        },
      ],
    },
    numbering: {
      config: [
        {
          reference: "report-bullets",
          levels: [
            {
              level: 0,
              format: LevelFormat.BULLET,
              text: "•",
              alignment: AlignmentType.LEFT,
              style: {
                paragraph: { indent: { left: 360, hanging: 180 } },
                run: { font: FONT, size: 24 },
              },
            },
          ],
        },
      ],
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: A4_WIDTH, height: A4_HEIGHT },
            margin: {
              top: PAGE_MARGIN,
              right: PAGE_MARGIN,
              bottom: PAGE_MARGIN,
              left: PAGE_MARGIN,
              header: 720,
              footer: 720,
              gutter: 0,
            },
          },
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({
                    font: FONT,
                    size: 20,
                    children: ["page ", PageNumber.CURRENT],
                  }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });

  fs.writeFileSync(OUTPUT_DOCX, await Packer.toBuffer(document));
  process.stdout.write(`${OUTPUT_DOCX}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
