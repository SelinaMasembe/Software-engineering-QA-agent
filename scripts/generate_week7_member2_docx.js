#!/usr/bin/env node

/** Generate the formal Week 7 Member 2 observability deliverable. */

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
  LineRuleType,
  Packer,
  PageBreak,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableLayoutType,
  TableOfContents,
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
const EVIDENCE_DIR = path.join(REPO_ROOT, "evidence/traces/observability");
const DEMO_SUMMARY = path.join(EVIDENCE_DIR, "week7-member2-demo-summary.json");
const DEMO_TIMELINE = path.join(EVIDENCE_DIR, "week7-member2-demo-timeline.txt");
const OUTPUT_DOCX = path.join(
  REPO_ROOT,
  "docs/integration/Week7_Member2_Observability.docx",
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

async function extractLetterhead() {
  const archive = await JSZip.loadAsync(fs.readFileSync(REFERENCE_DOCX));
  const entry = archive.file("word/media/image1.png");
  if (!entry) throw new Error("Reference letterhead image was not found.");
  return entry.async("nodebuffer");
}

function loadDemoEvidence() {
  const report = JSON.parse(fs.readFileSync(DEMO_SUMMARY, "utf8"));
  const timeline = fs.readFileSync(DEMO_TIMELINE, "utf8").split("\n");
  const byName = {};
  for (const run of report.runs) byName[run.scenario] = run;
  const section = (name) => {
    const start = timeline.findIndex((line) => line === `--- week7-demo-${name}`);
    if (start < 0) throw new Error(`Timeline for ${name} was not found.`);
    const lines = [];
    for (let i = start; i < timeline.length; i += 1) {
      if (i > start && timeline[i].startsWith("--- ")) break;
      if (timeline[i].trim()) lines.push(timeline[i]);
    }
    return lines;
  };
  return { report, byName, section };
}

function toolSummary(summary) {
  const tools = summary.tools.by_tool;
  const statuses = summary.tools.by_status;
  if (!summary.tools.calls) return "None";
  return `${Object.keys(tools).join(", ")}: ${Object.entries(statuses)
    .map(([status, count]) => `${count} ${status}`)
    .join(", ")}`;
}

async function main() {
  const letterhead = await extractLetterhead();
  const evidence = loadDemoEvidence();
  const runs = evidence.report.runs;
  for (const name of ["grounded-proposal", "not-in-corpus", "rejected-tool-recovery"]) {
    if (!evidence.byName[name]) throw new Error(`Demo scenario ${name} is missing.`);
  }

  const children = [];

  // Page 1: cover. Single, auto line spacing stops LibreOffice clipping the
  // letterhead under the document's default 1.15 line spacing.
  children.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 260, line: 240, lineRule: LineRuleType.AUTO },
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
    body("STEP-LEVEL OBSERVABILITY AND TELEMETRY", {
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
    body("WEEK 7: MEMBER 2 DELIVERABLE", {
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
    new TableOfContents("Contents", {
      headingStyleRange: "1-2",
      hyperlink: true,
      preserveTabInEntries: true,
      hideTabAndPageNumbersInWebView: true,
      useAppliedParagraphOutlineLevel: true,
      beginDirty: false,
      cachedEntries: [
        { title: "1 Purpose and Scope", level: 1, page: 3 },
        { title: "2 Ownership and Integration Boundaries", level: 1, page: 3 },
        { title: "3 Deliverable Location", level: 1, page: 4 },
        { title: "4 Observability Architecture", level: 1, page: 4 },
        { title: "4.1 Instrumented Seams", level: 2, page: 5 },
        { title: "5 What Each Step Records", level: 1, page: 5 },
        { title: "5.1 Metadata-Only Rule", level: 2, page: 6 },
        { title: "6 Behaviour-Preservation Guarantees", level: 1, page: 6 },
        { title: "7 Usage", level: 1, page: 7 },
        { title: "8 Evidence from the Offline Demonstration", level: 1, page: 7 },
        { title: "9 Files Implemented", level: 1, page: 8 },
        { title: "10 Verification", level: 1, page: 9 },
        { title: "10.1 Regression Checks", level: 2, page: 9 },
        { title: "11 AI Contribution", level: 1, page: 10 },
        { title: "11.1 Gates and Milestones", level: 2, page: 10 },
        { title: "11.2 Examples", level: 2, page: 11 },
        { title: "12 Limitations and Handoffs", level: 1, page: 12 },
        { title: "13 Conclusion", level: 1, page: 12 },
      ],
    }),
    pageBreak(),
  );

  // Purpose, scope and ownership.
  children.push(
    heading("1 Purpose and Scope"),
    body(
      "This report records Member 2's Week 7 contribution to the Software-Engineering QA Agent. The Team Task Allocation Plan assigns Member 2 to build the logging system that records what the model did, what it retrieved, which tools it called, and how long each step took. The Week 7 brief asks for logs and traces that capture useful model, prompt, retrieval, tool, latency, error and outcome evidence.",
    ),
    body(
      "The deliverable meets both with a step-telemetry recorder and a set of transparent wrappers around the components the agent already uses. One timed record is produced for every retrieval, context assembly, model call, planned action, tool dispatch, stop check and loop event. The records are written as JSON Lines evidence and summarised per session.",
    ),
    body(
      "The plan notes that Member 2 builds the layer that connects the pieces rather than every piece, so this work adds no new agent behaviour. It does not change the agent loop, the dispatcher, retrieval, the model client, Member 1's stop policy or Member 5's run logger. It does not create the evaluation scenarios, the scorer, the Failure Catalogue or the scenario runner, which belong to other members this week.",
    ),
    heading("2 Ownership and Integration Boundaries"),
    makeTable(
      ["Member", "Week 7 task", "Relationship to this deliverable"],
      [
        ["Member 1", "Traceability matrix; tests/test_scenario_coverage.py", "Not modified. Scenario IDs can be used as session IDs so each telemetry file maps to one scenario."],
        ["Member 2", "Logging system for model, retrieval, tool and timing evidence", "This deliverable."],
        ["Member 3", "Evaluation criteria; tests/adversarial/fixtures.py; src/evaluation/scorer.py", "Not modified. Plan and tool records provide inputs for groundedness and tool-use scoring."],
        ["Member 4", "Failure Catalogue; tests/test_failure_retest.py", "Not modified. Failed steps record where a failure happened and its exception type."],
        ["Member 5", "tests/run_scenarios.py; Week 7 progress report", "Not modified. recorder.summary() returns one JSON summary per run, and RunLogger still receives every trace entry."],
      ],
      [1500, 3600, 4647],
      { alternate: true },
    ),
    caption("Table 1: Week 7 ownership. Only the Member 2 row is implemented here."),
    pageBreak(),
  );

  // Location decision and architecture.
  children.push(
    heading("3 Deliverable Location"),
    body(
      "The plan names src/logging/observability.py. pytest.ini sets pythonpath = src and the README runs tests with PYTHONPATH=src, so a package called logging under src would be imported in place of Python's standard-library logging module and break any code that logs. Member 5 met the same issue in Week 5, when the plan's src/logging/tracer.py was delivered as src/observability/run_logger.py. This deliverable follows that precedent. It adds two new modules to the observability package and does not edit Member 5's files.",
    ),
    makeTable(
      ["Planned path", "Implemented as", "Contents"],
      [
        ["src/logging/observability.py", "src/observability/telemetry.py", "StepKind, StepRecord, ObservabilityRecorder, InMemoryStepSink, JsonlStepSink, load_steps and summarize."],
        ["", "src/observability/instrumentation.py", "Seven Observed* wrappers, InstrumentedLoopDependencies and instrument_loop."],
      ],
      [2900, 3150, 3697],
    ),
    caption("Table 2: Mapping from the planned path to the implemented modules."),
    heading("4 Observability Architecture"),
    body(
      "Each wrapper sits on a seam that already exists. The Week 5 AgentLoop receives its sensor, planner, dispatcher, stop evaluator and trace sink by dependency injection, so the loop is observed by passing wrapped collaborators to it, with no change to src/agent/loop.py. The model client and the retrieval pipeline are wrapped the same way because the planner and the sensor call them. All wrappers for one session share one ObservabilityRecorder, which numbers the records, times them and sends them to its sinks.",
    ),
    codeBlock([
      "AgentLoop (unchanged, Week 5)",
      "  |-- ObservedStopEvaluator -> Member 1 StopConditionPolicy     => stop_check",
      "  |-- ObservedSensor        -> sensor",
      "  |      `-- ObservedRetrievalPipeline -> RetrievalPipeline     => sense, retrieval",
      "  |-- ObservedPlanner       -> planner",
      "  |      `-- ObservedModelClient -> ChatCompletionsClient       => plan, model_call",
      "  |-- ObservedDispatcher    -> ToolDispatcher -> search_repo... => tool_call",
      "  `-- ObservedTraceSink     -> Member 5 RunLogger               => loop_event",
      "",
      "ObservabilityRecorder (one per session)",
      "  |-- InMemoryStepSink   tests and scenario runners",
      "  `-- JsonlStepSink      evidence/traces/observability/*.jsonl",
    ]),
    caption("Listing 1: Where the wrappers sit and the step kind each one records."),
    pageBreak(),
  );

  children.push(
    heading("4.1 Instrumented Seams", 2),
    makeTable(
      ["Wrapper", "Wrapped call", "Step kind"],
      [
        ["ObservedModelClient", "models.client.ModelClient.generate", "model_call"],
        ["ObservedRetrievalPipeline", "rag.RetrievalPipeline.retrieve", "retrieval"],
        ["ObservedSensor", "agent.ContextSensor.sense", "sense"],
        ["ObservedPlanner", "agent.Planner.plan", "plan"],
        ["ObservedDispatcher", "agent.Dispatcher.dispatch (ToolDispatcher)", "tool_call"],
        ["ObservedStopEvaluator", "agent.StopEvaluator.evaluate", "stop_check"],
        ["ObservedTraceSink", "agent.TraceSink.record (RunLogger)", "loop_event"],
      ],
      [3100, 4547, 2100],
      { alternate: true },
    ),
    caption("Table 3: The seven wrappers."),
    heading("5 What Each Step Records"),
    makeTable(
      ["Question", "Step kind", "Attributes recorded"],
      [
        ["What the model did", "model_call", "model, prompt_id, prompt_version, prompt_sha256, input/output/total tokens, provider_latency_ms, request_id, prompt and response sizes"],
        ["", "plan", "action, confidence, argument_keys, evidence_count, evidence_traceable, evidence_untraceable, rationale_chars"],
        ["What it retrieved", "retrieval", "not_in_corpus, candidates_considered, chunks (chunk_id, source_path, score), top_score, top_term_coverage, retrieval_latency_ms, corpus_version, corpus_fingerprint"],
        ["", "sense", "chunks_used, chunks_dropped, allowed_sources, context_chars, not_in_corpus"],
        ["Which tools it called", "tool_call", "tool, argument_keys, status, code, dispatcher_latency_ms, output_keys, output_bytes"],
        ["Why it stopped", "stop_check, loop_event", "decision, iterations_completed, loop event name, final outcome"],
        ["How long each step took", "every kind", "started_at, duration_ms, ok, error_type; per-kind count, errors, total, mean and maximum time; session elapsed_ms"],
      ],
      [2200, 1800, 5747],
      { alternate: true },
    ),
    caption("Table 4: Week 7 questions and the attributes that answer them."),
    body(
      "Every record also carries the session ID, a sequence number and the schema version qa-agent.step-telemetry/v1. ObservabilityRecorder.summary() reduces a session to one JSON object with timing per step kind, model calls, prompt versions, token totals, planned actions, retrieved sources, tool calls by name and status, the loop events and the final outcome.",
      { after: 0 },
    ),
    pageBreak(),
  );

  children.push(
    heading("5.1 Metadata-Only Rule", 2),
    body(
      "The records are designed to be committed as evidence, so they follow the metadata-only rule the Week 5 loop already applies to its trace entries.",
    ),
    bullet("Prompt text, retrieved text, tool argument values, tool output values and exception messages are never stored. A prompt is identified by its version and a SHA-256 fingerprint; a tool output by its key names and byte size."),
    bullet("Source paths are recorded when they come from deterministic retrieval. A path the model cites is copied only if it is in the turn's allowed set; any other cited path is only counted in evidence_untraceable, because model output is untrusted."),
    bullet("A failed step records the exception class name only."),
    bullet("Telemetry files use the .jsonl extension because scripts/check_sensitive.py blocks *.log files. Every evidence file passed that scan."),
    heading("6 Behaviour-Preservation Guarantees"),
    body(
      "Observability must not change what the agent decides. Each guarantee below is enforced in code and covered by a named test.",
    ),
    makeTable(
      ["Guarantee", "How it is enforced", "Test"],
      [
        ["Same result", "Wrappers forward the same arguments and return the wrapped component's result object.", "test_instrumented_run_matches_plain_run"],
        ["Same failure mapping", "step() records the exception type and re-raises the original exception object.", "test_component_failure_keeps_loop_failure_and_records_type_only"],
        ["Audit trail still fails closed", "ObservedTraceSink re-raises a sink error, so the loop still returns TRACE_FAILED.", "test_trace_sink_failure_still_fails_closed"],
        ["Telemetry never stops the agent", "A telemetry sink error is counted in dropped_writes and never raised.", "test_telemetry_sink_failure_does_not_change_the_run"],
        ["Runner check still works", "Unknown attributes such as ToolDispatcher.registry are read from the wrapped object.", "test_runner_accepts_an_instrumented_dispatcher"],
        ["Bad results do not raise", "Result attributes are read inside StepScope.capture; failures mark attributes_unavailable.", "test_capture_marks_unreadable_results_instead_of_raising"],
      ],
      [2300, 4100, 3347],
      { alternate: true },
    ),
    caption("Table 5: Guarantees that the instrumentation leaves agent behaviour unchanged."),
    pageBreak(),
  );

  // Usage and evidence.
  const grounded = evidence.byName["grounded-proposal"].summary;
  const noEvidence = evidence.byName["not-in-corpus"].summary;
  const rejected = evidence.byName["rejected-tool-recovery"].summary;
  children.push(
    heading("7 Usage"),
    codeBlock([
      "recorder = ObservabilityRecorder(session_id, sinks=[JsonlStepSink()])",
      "pipeline = ObservedRetrievalPipeline(retrieval_pipeline, recorder)",
      "client = ObservedModelClient(model_client, recorder,",
      "                             prompt_id=\"propose_action\", prompt_version=\"v1.2\")",
      "wrapped = instrument_loop(recorder, sensor=sensor, planner=planner,",
      "                          dispatcher=dispatcher, trace_sink=run_logger,",
      "                          stop_evaluator=stop_policy)",
      "result = AgentLoop(**wrapped.loop_kwargs()).run(task)",
      "summary = recorder.summary()",
    ]),
    caption("Listing 2: Observing one agent session."),
    body(
      "When a session is built with agent.runner.build_agent_session, the runner creates the stop evaluator from the task contract, so stop_evaluator is omitted and loop_kwargs() leaves it out. The runner's tool-registry check still passes because the wrapped dispatcher exposes the inner ToolDispatcher's registry.",
    ),
    heading("8 Evidence from the Offline Demonstration"),
    body(
      `scripts/member2_observability_demo.py runs three sessions. Everything except the model is a real project component: retrieval and the context builder over the Member 2 fixture corpus, Member 3's search_repo tool, the Week 4 ToolDispatcher, the Week 5 AgentLoop, Member 1's stop policy built by Member 3's task adapter, and the propose_action ${evidence.report.prompt_version} prompt file. A labelled DemoModelClient returns canned JSON, so no API key or network is needed. The script asserts each expected outcome and exits with an error if one is not reached.`,
    ),
    makeTable(
      ["Scenario", "Outcome", "Steps", "Model calls / tokens", "Retrievals", "Tool calls"],
      runs.map((runItem) => {
        const s = runItem.summary;
        const retrievalText = s.retrieval.not_in_corpus
          ? `${s.retrieval.calls} (${s.retrieval.not_in_corpus} not in corpus)`
          : String(s.retrieval.calls);
        return [
          runItem.scenario,
          runItem.status,
          String(s.steps),
          `${s.model.calls} / ${s.model.total_tokens}`,
          retrievalText,
          toolSummary(s),
        ];
      }),
      [2300, 1300, 900, 1700, 1500, 2047],
      { alternate: true },
    ),
    caption("Table 6: Demonstration results, read from evidence/traces/observability/week7-member2-demo-summary.json."),
    body(
      `The grounded run made ${grounded.model.calls} model calls and one executed search_repo call. The not-in-corpus run recorded retrieval with not_in_corpus = true and ended with no_action and ${noEvidence.tools.calls} tool calls. In the recovery run the dispatcher rejected a search_repo request with an unknown argument (${Object.keys(rejected.tools.by_status).join(", ")}), and the agent then completed on the next turn. Listing 3 shows that run's step timeline.`,
    ),
    pageBreak(),
  );

  children.push(
    codeBlock(evidence.section("rejected-tool-recovery")),
    caption("Listing 3: Step timeline for the rejected-tool-recovery run (evidence/traces/observability/week7-member2-demo-timeline.txt)."),
    body(
      "Token counts in the demonstration are estimated by the demo adapter (about four characters per token), because no provider is called. With ChatCompletionsClient they are the usage the provider reports. Durations are real measurements but very small, because the model is offline.",
    ),
    heading("9 Files Implemented"),
    makeTable(
      ["File", "Purpose"],
      [
        ["src/observability/telemetry.py", "Step kinds, immutable step records, the per-session recorder, in-memory and JSON Lines sinks, and the session summary."],
        ["src/observability/instrumentation.py", "Seven transparent wrappers and instrument_loop for the agent loop's collaborators."],
        ["tests/test_observability_telemetry.py", "14 unit tests: timing, failures, immutability, sinks, file naming, summary."],
        ["tests/integration/test_observability_agent_loop.py", "16 integration tests with the real AgentLoop, retrieval, ToolDispatcher, runner and RunLogger."],
        ["scripts/member2_observability_demo.py", "Offline three-scenario demonstration that writes the evidence files."],
        ["evidence/traces/observability/", "Three telemetry files, the demonstration summary and the step timeline."],
        ["scripts/generate_week7_member2_docx.js", "Generates this report from the committed evidence."],
        ["docs/ai-assistance credit/week7/member2-observability.md", "AI Engineering Log entry for this deliverable."],
      ],
      [4300, 5447],
      { alternate: true },
    ),
    caption("Table 7: Week 7 Member 2 files."),
    pageBreak(),
  );

  // Verification.
  children.push(
    heading("10 Verification"),
    makeTable(
      ["Command", "Result"],
      [
        ["pytest tests/test_observability_telemetry.py tests/integration/test_observability_agent_loop.py", "30 passed"],
        ["pytest (whole suite through pytest.ini)", "444 passed, 267 subtests passed (414 before this work)"],
        ["PYTHONPATH=src python -m unittest discover -s tests (README command)", "Ran 229 tests, OK"],
        ["python scripts/member2_observability_demo.py", "All three scenarios reached the expected outcome; exit code 0"],
        ["python scripts/check_sensitive.py on every new file", "No findings"],
      ],
      [5600, 4147],
      { alternate: true },
    ),
    caption("Table 8: Verification commands and results."),
    body(
      "The integration tests use the real agent loop, retrieval over the fixture corpus, the real context builder, the real citation validator, the real ToolDispatcher, agent.runner.build_agent_session and Member 5's RunLogger. Only the model, the tools and the stop policy are deterministic fakes in those tests.",
    ),
    heading("10.1 Regression Checks", 2),
    body(
      "To confirm that the tests detect real mistakes, the code was deliberately broken in four ways and the tests were run against each broken version.",
    ),
    makeTable(
      ["Deliberate defect", "Test that failed"],
      [
        ["Model-cited source paths copied verbatim", "test_fabricated_citation_is_counted_not_copied"],
        ["Tool output values copied into the record", "test_tool_call_records_name_status_and_output_size; test_secret_values_never_reach_the_telemetry_file"],
        ["Attribute delegation removed from the wrappers", "test_runner_accepts_an_instrumented_dispatcher"],
        ["Sinks written while the recorder lock is held (first version)", "test_sink_may_read_the_recorder_while_writing timed out (deadlock); fixed before submission"],
      ],
      [4300, 5447],
      { alternate: true },
    ),
    caption("Table 9: Each deliberate defect was caught by at least one test."),
    pageBreak(),
  );

  // AI contribution.
  children.push(
    heading("11 AI Contribution"),
    body([
      run("Model and tool. ", { bold: true }),
      run(
        "Claude Opus 5.5 (model ID claude-opus-5-5), used through Claude Code in this repository on the week7-observability-logging branch. Earlier Member 2 weeks used OpenAI Codex and Claude Code. Their session history was read at the start of Week 7 so that the same workflow, file layout and ownership boundaries were followed.",
      ),
    ]),
    body([run("How it was used (Member 2's account). ", { bold: true })], { after: 60 }),
    new Paragraph({
      alignment: AlignmentType.JUSTIFIED,
      indent: { left: 567, right: 567 },
      spacing: { after: 160, line: 276 },
      children: [
        run(
          "“I asked the AI for the work I had to do specifically as Member 2. Then I created the gates and milestones and let the agent implement them, while I tested at each gate and milestone to make sure it was doing the correct thing.”",
          { italics: true },
        ),
      ],
    }),
    body(
      "In practice, a milestone was one reviewable increment of code, tests or documentation, and a gate was the set of checks that had to pass before the next milestone started. Each passed milestone was committed separately, so the branch history shows every step.",
    ),
    heading("11.1 Gates and Milestones", 2),
    makeTable(
      ["Milestone", "What the agent implemented", "Gate check before moving on", "Commit"],
      [
        ["M1 Core recorder", "telemetry.py and its unit tests", "Unit tests pass; sensitive-data scan clean", "2b0205b"],
        ["M2 Instrumentation", "instrumentation.py and 16 integration tests", "Same loop result and trace entries with and without wrappers; whole suite passes; three deliberate defects caught", "2624783, 7a1da33"],
        ["M3 Demonstration", "Demo script and evidence files", "All three scenarios reach the expected outcome; evidence passes the sensitive-data scan", "4b3d22d, 1e2a832"],
        ["Review gate", "Fix for sink writes under the lock", "Deadlock reproduced on the old code; fixed code passes all 30 tests", "8fa18d6"],
        ["M4 Report and log", "This report and the AI Engineering Log", "Figures checked against test output and the committed evidence files", "Final commits"],
      ],
      [1800, 2700, 3847, 1400],
      { alternate: true },
    ),
    caption("Table 10: Milestones, gate checks and the commits that passed them."),
    pageBreak(),
  );

  children.push(
    heading("11.2 Examples", 2),
    bullet("Scope instruction. Member 2 asked the agent to respect the work boundaries and do only Member 2's work. The agent read the Team Task Allocation Plan and the Week 7 brief, picked out Member 2's row, and left Member 1's coverage script, Member 3's scorer and adversarial fixtures, Member 4's Failure Catalogue and Member 5's scenario runner untouched."),
    bullet("Following the earlier workflow. The agent read the Week 5 and Week 6 Codex sessions and reused their pattern: implementation first, focused tests, a review round, then a generated Word deliverable and an AI log."),
    bullet("Path decision. Before writing code, the agent reported that src/logging would shadow the standard-library logging module and proposed the src/observability package Member 5 used in Week 5. The decision is recorded in Section 3."),
    bullet("Test expectations corrected at Gate 2. Three integration tests failed on the first run because the fixture corpus also returned its test-log file and a shortened goal found no evidence. The tests were corrected to match real retrieval; the code did not change."),
    bullet("Defect found at the review gate. Sinks were written while the recorder lock was held, so a sink that read the summary would deadlock. A new test reproduced the hang on the old code before the fix was accepted."),
    bullet("Option rejected. Recording model-cited source paths verbatim was rejected because model output is untrusted; cited paths outside the allowed set are counted instead."),
    bullet("Branch and commits. Member 2 asked for a branch name without the words claude or ai, and for incremental commits. The work landed as small commits on week7-observability-logging."),
    body(
      "All generated code was reviewed and tested before it was committed. No API keys, credentials or personal data were sent to the model; the demonstration uses the team's fixture corpus and an offline model adapter. Responsibility for the submitted code, tests and documentation remains with Member 2.",
      { after: 0 },
    ),
    pageBreak(),
  );

  // Limitations and conclusion.
  children.push(
    heading("12 Limitations and Handoffs"),
    bullet("The demonstration uses an offline model adapter, so provider latency is zero and token counts are estimates. With ChatCompletionsClient the recorded values come from the provider's response."),
    bullet("No production entry point composes the agent yet. Callers opt in by wrapping collaborators as shown in Section 7."),
    bullet("Nested steps overlap: sense includes retrieval and plan includes the model call. Per-kind totals must not be added together; elapsed_ms gives the session total."),
    bullet("Telemetry files are flushed but not fsynced. They are evaluation evidence; the fail-closed audit trail remains Member 5's RunLogger."),
    bullet("ToolDispatcher.dispatch_raw is reachable through attribute delegation but is not timed; the agent loop calls dispatch only."),
    bullet("Create one recorder per session and reuse it when resuming a paused session; JsonlStepSink then continues the same file."),
    makeTable(
      ["Owner", "Suggested use of this deliverable"],
      [
        ["Member 5 (tests/run_scenarios.py)", "Create one ObservabilityRecorder per scenario, using the scenario ID as the session ID, and collect summary() into the aggregated results."],
        ["Member 3 (src/evaluation/scorer.py)", "Use evidence_traceable and evidence_untraceable for groundedness, and tool_call status and code for tool-use scoring."],
        ["Member 4 (tests/test_failure_retest.py)", "Use error_type and the step order to show where a failure happened before and after its fix."],
        ["Member 1 (traceability matrix)", "Map telemetry files to scenarios and user stories through the session ID."],
      ],
      [3300, 6447],
      { alternate: true },
    ),
    caption("Table 11: Handoffs to the other Week 7 owners."),
    heading("13 Conclusion"),
    body(
      "The Week 7 Member 2 deliverable records, for every agent session, what the model did, what was retrieved, which tools were called and how long each step took, as metadata-only JSON Lines evidence with a per-session summary. It wraps existing seams instead of changing them, and tests show the agent reaches the same outcomes with or without it. The recorder and its summary are ready for the scenario runner, scorer and failure re-tests that the other members are building this week.",
      { after: 0 },
    ),
  );

  const document = new Document({
    title: "Week 7 Member 2 Step-Level Observability",
    subject: "BSE4104 AI-Native and Agentic Engineering Capstone",
    creator: "Akanga Andrew",
    description: "Formal Week 7 Member 2 deliverable for step-level observability and telemetry.",
    keywords: "BSE4104, observability, telemetry, tracing, latency, QA agent, Group J",
    features: { updateFields: true },
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
        {
          id: "TOC1",
          name: "TOC 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { font: FONT, size: 22, color: "000000" },
          paragraph: {
            spacing: { after: 90, line: 240 },
          },
        },
        {
          id: "TOC2",
          name: "TOC 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { font: FONT, size: 21, color: "000000" },
          paragraph: {
            indent: { left: 360 },
            spacing: { after: 70, line: 240 },
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
