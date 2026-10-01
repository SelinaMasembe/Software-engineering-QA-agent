#!/usr/bin/env node

/** Generate the formal Week 5 Member 2 agent-loop deliverable. */

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
  "docs/architecture/l5-agent-loop.png",
);
const OUTPUT_DOCX = path.join(
  REPO_ROOT,
  "docs/integration/Week5_Member2_AgentLoop.docx",
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
        // Mark the single-row code panel so accessibility tooling does not
        // interpret it as a data table with an omitted header row.
        tableHeader: true,
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
    body("AGENT LOOP ORCHESTRATION AND CITATION SAFETY", {
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
    body("WEEK 5 — MEMBER 2 DELIVERABLE", {
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
    tocLine("1 Purpose and Scope", 3),
    tocLine("2 Ownership and Integration Boundaries", 3),
    tocLine("3 Agent Loop Architecture", 4),
    tocLine("4 Execution Lifecycle", 5),
    tocLine("5 Citation Validator Change", 6),
    tocLine("6 Dependency Contracts", 7),
    tocLine("7 Files Implemented", 7),
    tocLine("8 Verification", 8),
    tocLine("9 Limitations and Handoffs", 9),
    tocLine("10 Conclusion", 9),
    pageBreak(),
  );

  // Page 3: purpose, scope and ownership.
  children.push(
    heading("1 Purpose and Scope"),
    body(
      "This report records Member 2's Week 5 contribution to the Software-Engineering QA Agent. The deliverable is a bounded agent loop that coordinates the existing retrieval, model, citation-validation, dispatcher, stop-policy and tracing boundaries without re-implementing those components. One iteration senses context, plans exactly one proposal, validates its citations, acts through the established dispatcher when required, records a safe observation, and either stops, pauses or begins another iteration.",
    ),
    body(
      "The loop accepts a validated runtime AgentTask. It does not parse task_contract.yaml, define the stop policy, implement production tools, decide human approval, or persist trace records. These limits preserve the intended team structure and keep the Week 5 work focused on orchestration.",
    ),
    heading("2 Ownership and Integration Boundaries"),
    makeTable(
      ["Component", "Responsibility in this deliverable", "Boundary"],
      [
        ["AgentLoop", "Member 2 implementation", "Coordinates one bounded session and returns a stable LoopResult."],
        ["ContextSensor and RAG", "Injected dependency", "Returns AssembledContext and the exact citation allow-list."],
        ["Planner and model client", "Injected dependency", "Returns one ProposalSet for the current turn."],
        ["Citation validator", "Reused and narrowly updated", "Rejects missing or fabricated evidence before dispatch."],
        ["ToolDispatcher and approval gate", "Existing Week 4 boundary", "Authorizes, approves and invokes at most one tool."],
        ["StopEvaluator and TraceSink", "Injected team dependencies", "Own stop decisions and trace persistence."],
      ],
      [2300, 2850, 4597],
      { alternate: true },
    ),
    caption("Table 1: Week 5 Member 2 ownership and integration boundaries."),
    pageBreak(),
  );

  // Page 4: architecture.
  children.push(
    heading("3 Agent Loop Architecture"),
    body(
      "Figure 1 records the L5 application-layer lifecycle. Solid outlines inside AgentLoop identify Member 2 stages. Dashed boxes are injected dependencies owned elsewhere in the team structure. The loop cannot widen tool permissions, bypass approval, change citation sources, or override a stop decision.",
    ),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 60, after: 60 },
      children: [
        new ImageRun({
          data: architecture,
          type: "png",
          transformation: { width: 650, height: 554 },
          altText: {
            title: "L5 agent loop architecture",
            description: "Sense, plan, validate, act, observe and stop-or-repeat lifecycle with injected dependencies.",
            name: "L5 agent loop architecture",
          },
        }),
      ],
    }),
    caption(
      "Figure 1: L5 agent-loop architecture — solid stages are Member 2; dashed boxes are injected team dependencies.",
    ),
    body(
      "The action branch is deliberate: PROPOSE_TEST and NO_ACTION complete directly after citation validation; only actions in TOOL_ACTIONS reach ToolDispatcher. Every tool iteration therefore contains one proposal and no more than one dispatch.",
      { after: 0 },
    ),
    pageBreak(),
  );

  // Page 5: lifecycle and outcomes.
  children.push(
    heading("4 Execution Lifecycle"),
    makeTable(
      ["Stage", "Implemented behaviour"],
      [
        ["1. Stop check", "Runs before the first turn and after each recorded observation; a decision halts without another model or tool call."],
        ["2. Sense", "Snapshots AssembledContext and its allowed_source_paths before planning."],
        ["3. Plan", "Accepts exactly one ProposalSet and stores a detached, immutable PlannedAction."],
        ["4. Validate", "Checks every citation against this turn's allow-list before any dispatch."],
        ["5. Act", "Completes direct actions or sends one tool action through ToolDispatcher."],
        ["6. Observe", "Records a bounded, immutable and sanitized outcome without raw exception text."],
        ["7. Stop or repeat", "Halts, pauses for approval, completes, fails safely, or begins the next turn."],
      ],
      [2050, 7697],
      { alternate: true },
    ),
    caption("Table 2: Sense–plan–validate–act–observe lifecycle."),
    makeTable(
      ["Outcome", "Meaning and dispatch effect"],
      [
        ["COMPLETED", "A grounded PROPOSE_TEST is ready for human review; no dispatcher call."],
        ["NO_ACTION", "A grounded or deterministically justified no-action result; no dispatcher call."],
        ["AWAITING_APPROVAL", "The request is paused and resumable; the loop never auto-resubmits it."],
        ["HALTED", "The injected stop evaluator ended the session; no further calls occur."],
        ["FAILED", "A required dependency failed; the result uses a fixed LoopFailure value."],
        ["Tool rejection or error", "A safe observation is added, then the stop evaluator decides whether another turn is permitted."],
      ],
      [2700, 7047],
      { alternate: true },
    ),
    caption("Table 3: Loop outcomes and dispatch effects."),
    heading("4.1 Safety Invariants", 2),
    bullet("Exactly one planned proposal enters each iteration."),
    bullet("At most one dispatcher call can occur in each iteration."),
    bullet("Citation validation always occurs before direct completion or tool dispatch."),
    bullet("Approval-pending results pause rather than retry or auto-approve."),
    pageBreak(),
  );

  // Page 6: citation validator.
  children.push(
    heading("5 Citation Validator Change"),
    body(
      "The existing citation validator originally required evidence for every proposal. That rule conflicts with the propose_action failure behaviour when deterministic retrieval confirms that the requested information is not in the corpus: NO_ACTION is the only honest response, and there is no source path available to cite. Forcing evidence in that case would encourage a fabricated citation.",
    ),
    body(
      "The validator now accepts a keyword-only confirmed_not_in_corpus flag. Evidence-free NO_ACTION passes only when that value is exactly true and the allowed source-path set is empty. The flag is derived from AssembledContext.not_in_corpus, not from model output. All other evidence-free proposals remain rejected, and every supplied citation must still occur in the current turn's exact allow-list.",
    ),
    codeBlock([
      "validate_citations(",
      "    proposal,",
      "    allowed_source_paths,",
      "    *,",
      "    confirmed_not_in_corpus=False,",
      ")",
    ]),
    caption("Listing 1: Citation-validation interface with the narrow Week 5 flag."),
    makeTable(
      ["Proposal state", "Validator decision"],
      [
        ["Evidence matches the current allow-list", "Accept."],
        ["Evidence is missing for any tool action or PROPOSE_TEST", "Reject before dispatch."],
        ["Evidence cites a path outside the current allow-list", "Reject as fabricated or untraceable."],
        ["NO_ACTION, no evidence, retrieval confirmed empty, allow-list empty", "Accept the narrow exception."],
        ["NO_ACTION uses the flag but supplies a citation", "Reject if that citation is not traceable; the flag never validates a path."],
      ],
      [4700, 5047],
      { alternate: true },
    ),
    caption("Table 4: Citation-validator decisions."),
    body(
      "The module docstring and inline comments document the prompt failure behaviour, the deterministic source of the flag, and why a truthy non-boolean value must not open the exception.",
      { after: 0 },
    ),
    pageBreak(),
  );

  // Page 7: contracts and files.
  children.push(
    heading("6 Dependency Contracts"),
    makeTable(
      ["Contract", "Expected value", "Failure classification"],
      [
        ["ContextSensor.sense", "AssembledContext", "SENSE_FAILED"],
        ["Planner.plan", "One structurally valid ProposalSet", "PLAN_FAILED"],
        ["Citation validation", "Traceable proposal or narrow NO_ACTION", "Expected rejection is observed; validator fault is VALIDATION_FAILED"],
        ["Dispatcher.dispatch", "DispatchResult for a tool action", "DISPATCH_FAILED"],
        ["StopEvaluator.evaluate", "StopReason or None", "STOP_CHECK_FAILED"],
        ["TraceSink.record", "Successful metadata-only recording", "TRACE_FAILED"],
      ],
      [2700, 3950, 3097],
      { alternate: true },
    ),
    caption("Table 5: Injected contracts and sanitized failure mapping."),
    heading("7 Files Implemented"),
    makeTable(
      ["File", "Purpose"],
      [
        ["src/agent/loop.py", "Implements AgentLoop, immutable state/result types, dependency protocols and safe lifecycle handling."],
        ["src/agent/__init__.py", "Exports the public Week 5 agent-loop boundary."],
        ["src/orchestrator/validation.py", "Adds and documents the narrow evidence-free NO_ACTION exception."],
        ["tests/integration/test_agent_loop.py", "Covers lifecycle, outcomes, invariants, failures, pause/resume and safe tracing."],
        ["tests/test_validation.py", "Covers accepted, missing, fabricated and confirmed-empty citation cases."],
        ["docs/architecture/qa-agent-architecture (1).drawio", "Adds the editable L5 · Agent loop page."],
        ["docs/architecture/l5-agent-loop.png", "Provides the rendered architecture image used in Figure 1."],
      ],
      [3900, 5847],
      { alternate: true },
    ),
    caption("Table 6: Week 5 Member 2 implementation and evidence files."),
    pageBreak(),
  );

  // Page 8: verification.
  children.push(
    heading("8 Verification"),
    body(
      "The focused Member 2 unit suite completed 40 tests successfully. A broader integration selection completed 74 tests and 116 subtests successfully. Python compilation, whitespace validation and the repository sensitive-data check also passed for the changed source and test files.",
    ),
    makeTable(
      ["Verification area", "Evidence covered"],
      [
        ["Normal lifecycle", "Sense, plan, validate, dispatch, observe, re-plan and complete."],
        ["Direct outcomes", "PROPOSE_TEST and NO_ACTION complete with zero dispatcher calls."],
        ["Citation safety", "Missing and fabricated evidence never reaches the dispatcher; the confirmed-empty exception is narrow."],
        ["Approval", "Pending approval pauses, is marked resumable and never auto-resubmits."],
        ["Failures", "Sensor, planner, validator, dispatcher, stop evaluator and trace sink failures are sanitized."],
        ["Data boundaries", "Proposals and outputs are copied, frozen, JSON-checked and size-bounded."],
      ],
      [3100, 6647],
      { alternate: true },
    ),
    caption("Table 7: Focused verification coverage."),
    codeBlock([
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest \\",
      "  tests.integration.test_agent_loop tests.test_validation -v",
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q \\",
      "  tests/integration/test_agent_loop.py tests/test_validation.py \\",
      "  tests/integration/test_router.py tests/test_tool_auth.py",
    ]),
    heading("8.1 Repository-Wide Baseline", 2),
    body(
      "The repository-wide suite is not claimed as fully passing. The tests directory currently has a pre-existing RAG manifest-count failure, and unscoped root discovery also collects test modules stored under the example knowledge corpus. These issues are outside the Week 5 agent-loop boundary and are recorded rather than hidden.",
      { after: 0 },
    ),
    pageBreak(),
  );

  // Page 9: limits and conclusion.
  children.push(
    heading("9 Limitations and Handoffs"),
    bullet("The loop receives an already validated AgentTask; task_contract.yaml parsing and validation remain outside src/agent/loop.py."),
    bullet("StopEvaluator is injected. The loop enforces its decision but does not define iteration, wall-clock, repetition or no-new-information policy."),
    bullet("TraceSink is injected. The loop emits metadata-only TraceEntry values but does not persist them."),
    bullet("Tool authentication, authorization, approval and output-schema checks remain inside the established dispatcher and tool boundaries."),
    bullet("A caller resumes an approval-pending result explicitly; the loop does not poll, replay or auto-approve the pending request."),
    bullet("The architecture records intended adapters and handoffs without claiming they are implemented by Member 2."),
    heading("9.1 Team Integration Actions", 2),
    makeTable(
      ["Owner", "Required handoff"],
      [
        ["Task-contract owner", "Parse and validate task_contract.yaml, then construct AgentTask with the goal and ExecutionContext."],
        ["RAG/context owner", "Provide AssembledContext with exact allowed_source_paths and deterministic not_in_corpus."],
        ["Stop-policy owner", "Supply StopEvaluator.evaluate using the agreed bounded-stop rules."],
        ["Tracing owner", "Persist TraceEntry metadata without introducing raw arguments, outputs or exception text."],
        ["Integration/test owner", "Run the full scenario and failure matrix once all adapters are connected."],
      ],
      [2500, 7247],
      { alternate: true },
    ),
    caption("Table 8: Remaining team integration actions."),
    heading("10 Conclusion"),
    body(
      "The Week 5 Member 2 deliverable provides a bounded, dependency-injected agent loop that preserves citation, authorization, approval, stopping and trace boundaries. Its one-proposal and at-most-one-dispatch rules make each turn auditable, while safe pause, halt and failure results prevent uncontrolled continuation. The citation exception resolves the empty-corpus prompt case without weakening evidence checks for any actionable proposal.",
      { after: 0 },
    ),
  );

  const document = new Document({
    title: "Week 5 Member 2 Agent Loop Orchestration",
    subject: "BSE4104 AI-Native and Agentic Engineering Capstone",
    creator: "Akanga Andrew",
    description: "Formal Week 5 Member 2 deliverable for the bounded agent loop and citation safety.",
    keywords: "BSE4104, agent loop, orchestration, citation validation, QA agent, Group J",
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
