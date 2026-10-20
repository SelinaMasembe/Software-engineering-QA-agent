"""The real ContextSensor: retrieval plus build_context, with flags traced.

Week 8, Member 3. ``RetrievalContextSensor`` satisfies the ``ContextSensor``
protocol in ``agent.loop``: it builds a retrieval query from the task, asks
the retrieval pipeline for ranked chunks, and returns exactly what
``rag.context_builder.build_context`` produces, so the model-visible text is
the same as everywhere else in the system.

Flags. ``build_context`` puts injection and credential flags on the context
(``AssembledContext.flagged``). ``AgentLoop`` records them itself as a
``context_flagged`` trace entry, so inside the loop give the sensor no sink,
or every flag is recorded twice. The optional sink is for using the sensor
outside ``AgentLoop``: it then records one ``injection_flagged`` entry per
call that has flags, built by ``rag.injection_flagging.flag_trace_entry``:
counts, rule ids and categories only, never chunk text or a source path. A
sink failure never breaks sensing; it is counted in ``sink_failures``
instead, because ``AssembledContext`` has no field to carry it.

Query. ``AgentTask`` carries only a goal, so the query is the goal text
(``retrieval_query``). It is a separate function so it can be replaced. With
the shipped task contract the goal is the prompt's ROLE text, which matches
nothing specific in the corpus: a real session needs a specific goal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from rag.context_builder import AssembledContext, build_context
from rag.injection_flagging import flag_trace_entry

from .loop import AgentTask, LoopState, TraceSink


def retrieval_query(task: AgentTask) -> str:
    """The query for this turn: the task's goal text, trimmed."""

    return task.goal.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RetrievalContextSensor:
    """ContextSensor backed by a retrieval pipeline and ``build_context``."""

    def __init__(
        self,
        pipeline: Any,
        *,
        trace_sink: TraceSink | None = None,
        clock: Callable[[], datetime] = _utc_now,
        query_builder: Callable[[AgentTask], str] = retrieval_query,
    ) -> None:
        if not hasattr(pipeline, "retrieve"):
            raise ValueError("RetrievalContextSensor needs a pipeline with retrieve().")
        if not callable(clock) or not callable(query_builder):
            raise ValueError("clock and query_builder must be callables.")
        self.pipeline = pipeline
        self.trace_sink = trace_sink
        self.clock = clock
        self.query_builder = query_builder
        self.sink_failures = 0

    def sense(self, task: AgentTask, state: LoopState) -> AssembledContext:
        context = build_context(self.pipeline.retrieve(self.query_builder(task)))
        if context.flagged and self.trace_sink is not None:
            try:
                entry = flag_trace_entry(task.context.session_id, context.flagged, self.clock())
                self.trace_sink.record(entry)
            except Exception:
                # Tracing the flags must never stop the agent from seeing its
                # evidence. The flags stay on the context either way.
                self.sink_failures += 1
        return context


__all__ = ["RetrievalContextSensor", "retrieval_query"]
