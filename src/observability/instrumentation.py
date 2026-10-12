"""Wrap the agent's existing components so every step is timed and recorded.

This is the second half of the Week 7 Member 2 observability layer (the
recorder is in ``observability.telemetry``). Each wrapper sits on a seam that
already exists and records one ``StepRecord`` per call:

- ``ObservedModelClient`` around ``models.client.ModelClient.generate``;
- ``ObservedRetrievalPipeline`` around ``rag.RetrievalPipeline.retrieve``;
- ``ObservedSensor``, ``ObservedPlanner``, ``ObservedDispatcher``,
  ``ObservedStopEvaluator`` and ``ObservedTraceSink`` around the five
  collaborators ``agent.AgentLoop`` is built with.

The wrappers are transparent. They pass the same arguments through, return
the wrapped component's result object unchanged and re-raise its exception
unchanged, so ``AgentLoop`` still reaches the same outcome and still maps a
failure to the same ``LoopFailure``. Any attribute a wrapper does not define
is read from the wrapped object, so ``agent.runner`` still finds
``ToolDispatcher.registry`` behind an ``ObservedDispatcher``.

What is recorded follows the metadata-only rule ``AgentLoop`` already uses
for its trace entries: names, enums, counts, sizes, durations and the source
paths deterministic retrieval returned. Prompt text, retrieved text, argument
values and output values are never copied. Paths the model cites are kept
only when they are in the turn's allowed set; any other cited path is only
counted, because model output is untrusted and could carry anything.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from observability.telemetry import ObservabilityRecorder, StepKind


class _Observed:
    """Shared plumbing: argument checks and attribute delegation."""

    def __init__(
        self,
        inner: Any,
        recorder: ObservabilityRecorder,
        method: str,
        label: str,
    ) -> None:
        if not callable(getattr(inner, method, None)):
            raise ValueError(f"Instrumentation requires a {label}.")
        if not isinstance(recorder, ObservabilityRecorder):
            raise ValueError("Instrumentation requires an ObservabilityRecorder.")
        self._inner = inner
        self._recorder = recorder

    @property
    def wrapped(self) -> Any:
        """The component this wrapper records."""

        return self._inner

    def __getattr__(self, name: str) -> Any:
        # Only reached when normal lookup fails, e.g. ``registry`` on a
        # wrapped ToolDispatcher, which agent.runner checks for.
        inner = self.__dict__.get("_inner")
        if inner is None or name.startswith("__"):
            raise AttributeError(name)
        return getattr(inner, name)


class ObservedModelClient(_Observed):
    """Records model id, prompt version, token usage and latency per call."""

    def __init__(
        self,
        inner: Any,
        recorder: ObservabilityRecorder,
        *,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        super().__init__(inner, recorder, "generate", "model client")
        for label, value in (("prompt_id", prompt_id), ("prompt_version", prompt_version)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{label} must be a non-empty string when given.")
        self._prompt_id = prompt_id
        self._prompt_version = prompt_version

    def generate(self, *, system_prompt: str, user_content: str) -> Any:
        with self._recorder.step(StepKind.MODEL_CALL) as scope:
            scope.capture(
                lambda: {
                    "prompt_id": self._prompt_id,
                    "prompt_version": self._prompt_version,
                    # Identifies the exact prompt text without storing it.
                    "prompt_sha256": _fingerprint(system_prompt),
                    "system_prompt_chars": len(system_prompt),
                    "user_content_chars": len(user_content),
                }
            )
            result = self._inner.generate(
                system_prompt=system_prompt, user_content=user_content
            )
            scope.capture(lambda: _model_result_attributes(result))
            return result


class ObservedRetrievalPipeline(_Observed):
    """Records what retrieval returned: sources, scores and not-in-corpus."""

    def __init__(self, inner: Any, recorder: ObservabilityRecorder) -> None:
        super().__init__(inner, recorder, "retrieve", "retrieval pipeline")

    def retrieve(self, query: str, **options: Any) -> Any:
        with self._recorder.step(StepKind.RETRIEVAL) as scope:
            scope.capture(
                lambda: {
                    "query_chars": len(query),
                    "path_scope": options.get("path_scope"),
                    "top_k": options.get("top_k"),
                }
            )
            result = self._inner.retrieve(query, **options)
            scope.capture(lambda: _retrieval_attributes(result))
            return result


class ObservedSensor(_Observed):
    """``agent.ContextSensor`` wrapper: times sensing and records the context.

    The time includes any retrieval the sensor performs, which is also
    recorded separately when the sensor uses an ``ObservedRetrievalPipeline``.
    """

    def __init__(self, inner: Any, recorder: ObservabilityRecorder) -> None:
        super().__init__(inner, recorder, "sense", "context sensor")

    def sense(self, task: Any, state: Any) -> Any:
        with self._recorder.step(StepKind.SENSE) as scope:
            scope.capture(lambda: {"iteration": state.iterations_completed + 1})
            context = self._inner.sense(task, state)
            scope.capture(lambda: _context_attributes(context))
            return context


class ObservedPlanner(_Observed):
    """``agent.Planner`` wrapper: records the one action the model chose.

    The time includes the model call, which is also recorded separately when
    the planner uses an ``ObservedModelClient``.
    """

    def __init__(self, inner: Any, recorder: ObservabilityRecorder) -> None:
        super().__init__(inner, recorder, "plan", "planner")

    def plan(self, task: Any, context: Any, state: Any) -> Any:
        with self._recorder.step(StepKind.PLAN) as scope:
            scope.capture(lambda: {"iteration": state.iterations_completed + 1})
            proposal = self._inner.plan(task, context, state)
            scope.capture(lambda: _proposal_attributes(proposal, context))
            return proposal


class ObservedDispatcher(_Observed):
    """``agent.Dispatcher`` wrapper: records which tool ran and its outcome."""

    def __init__(self, inner: Any, recorder: ObservabilityRecorder) -> None:
        super().__init__(inner, recorder, "dispatch", "dispatcher")

    def dispatch(self, proposal: Any, *, context: Any) -> Any:
        with self._recorder.step(StepKind.TOOL_CALL) as scope:
            scope.capture(
                lambda: {
                    "tool": _value(proposal.action),
                    "argument_keys": _sorted_keys(proposal.arguments),
                }
            )
            result = self._inner.dispatch(proposal, context=context)
            scope.capture(lambda: _dispatch_attributes(result))
            return result


class ObservedStopEvaluator(_Observed):
    """``agent.StopEvaluator`` wrapper: records each stop decision."""

    def __init__(self, inner: Any, recorder: ObservabilityRecorder) -> None:
        super().__init__(inner, recorder, "evaluate", "stop evaluator")

    def evaluate(self, state: Any) -> Any:
        with self._recorder.step(StepKind.STOP_CHECK) as scope:
            scope.capture(
                lambda: {"iterations_completed": state.iterations_completed}
            )
            decision = self._inner.evaluate(state)
            scope.capture(
                lambda: {
                    "decision": None if decision is None else _value(decision),
                    "halt": decision is not None,
                }
            )
            return decision


class ObservedTraceSink(_Observed):
    """``agent.TraceSink`` wrapper: forwards every entry, records the event.

    Member 5's ``RunLogger`` (or any sink) still receives the identical
    ``TraceEntry``. If it raises, the error is re-raised so the loop still
    fails closed with ``LoopFailure.TRACE_FAILED``.
    """

    def __init__(self, inner: Any, recorder: ObservabilityRecorder) -> None:
        super().__init__(inner, recorder, "record", "trace sink")

    def record(self, entry: Any) -> None:
        with self._recorder.step(StepKind.LOOP_EVENT) as scope:
            scope.capture(
                lambda: {
                    "event": entry.action,
                    "actor": _value(entry.actor),
                    "tool_invocation": entry.tool_invocation is not None,
                }
            )
            self._inner.record(entry)


@dataclass(frozen=True)
class InstrumentedLoopDependencies:
    """The wrapped collaborators to build ``agent.AgentLoop`` with."""

    sensor: ObservedSensor
    planner: ObservedPlanner
    dispatcher: ObservedDispatcher
    trace_sink: ObservedTraceSink
    stop_evaluator: ObservedStopEvaluator | None = None

    def loop_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``AgentLoop``; omits an unwrapped stop evaluator."""

        kwargs: dict[str, Any] = {
            "sensor": self.sensor,
            "planner": self.planner,
            "dispatcher": self.dispatcher,
            "trace_sink": self.trace_sink,
        }
        if self.stop_evaluator is not None:
            kwargs["stop_evaluator"] = self.stop_evaluator
        return kwargs


def instrument_loop(
    recorder: ObservabilityRecorder,
    *,
    sensor: Any,
    planner: Any,
    dispatcher: Any,
    trace_sink: Any,
    stop_evaluator: Any | None = None,
) -> InstrumentedLoopDependencies:
    """Wrap the agent loop's collaborators so one recorder sees every step.

    ``stop_evaluator`` is optional because ``agent.runner.build_agent_session``
    builds its own from the task contract; pass it when constructing
    ``AgentLoop`` directly.
    """

    return InstrumentedLoopDependencies(
        sensor=ObservedSensor(sensor, recorder),
        planner=ObservedPlanner(planner, recorder),
        dispatcher=ObservedDispatcher(dispatcher, recorder),
        trace_sink=ObservedTraceSink(trace_sink, recorder),
        stop_evaluator=(
            None
            if stop_evaluator is None
            else ObservedStopEvaluator(stop_evaluator, recorder)
        ),
    )


# ---------------------------------------------------------------------------
# Attribute readers. Each one runs inside ``StepScope.capture``, so a result
# of the wrong shape marks the step ``attributes_unavailable`` and the
# component's own outcome is left for the agent loop to handle.
# ---------------------------------------------------------------------------


def _model_result_attributes(result: Any) -> dict[str, Any]:
    usage = result.usage
    return {
        "model": result.model,
        "provider_latency_ms": result.latency_ms,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "request_id": result.request_id,
        "response_chars": len(result.raw_text),
    }


def _retrieval_attributes(result: Any) -> dict[str, Any]:
    chunks = [
        {
            "chunk_id": retrieved.chunk.chunk_id,
            "source_path": retrieved.chunk.source_path,
            "score": round(float(retrieved.score), 4),
        }
        for retrieved in result.chunks
    ]
    return {
        "not_in_corpus": result.not_in_corpus is True,
        "candidates_considered": result.candidates_considered,
        "chunks_returned": len(chunks),
        "top_score": round(float(result.top_score), 4),
        "top_term_coverage": round(float(result.top_term_coverage), 4),
        "retrieval_latency_ms": result.latency_ms,
        "corpus_version": result.manifest.corpus_version,
        "corpus_fingerprint": result.manifest.corpus_fingerprint,
        "chunks": chunks,
        "source_paths": sorted({chunk["source_path"] for chunk in chunks}),
    }


def _context_attributes(context: Any) -> dict[str, Any]:
    return {
        "not_in_corpus": context.not_in_corpus is True,
        "chunks_used": context.chunks_used,
        "chunks_dropped": context.chunks_dropped,
        "context_chars": len(context.text),
        "allowed_sources": sorted(_allowed_paths(context)),
    }


def _proposal_attributes(proposal: Any, context: Any) -> dict[str, Any]:
    cited = {ref.source_path for ref in proposal.evidence}
    try:
        allowed = _allowed_paths(context)
    except Exception:
        allowed = frozenset()
    return {
        "action": _value(proposal.action),
        "confidence": _value(proposal.confidence),
        "argument_keys": _sorted_keys(proposal.arguments),
        "rationale_chars": len(proposal.rationale),
        "evidence_count": len(proposal.evidence),
        "evidence_traceable": sorted(path for path in cited if path in allowed),
        "evidence_untraceable": sum(1 for path in cited if path not in allowed),
    }


def _dispatch_attributes(result: Any) -> dict[str, Any]:
    output = result.output
    return {
        "status": _value(result.status),
        "code": None if result.code is None else _value(result.code),
        "dispatcher_latency_ms": result.latency_ms,
        "output_keys": None if output is None else _sorted_keys(output),
        "output_bytes": None if output is None else len(_encode_json(output)),
    }


def _allowed_paths(context: Any) -> frozenset[str]:
    paths = context.allowed_source_paths
    if isinstance(paths, str):
        raise TypeError("Allowed source paths must be a collection.")
    return frozenset(path for path in paths if isinstance(path, str))


def _sorted_keys(mapping: Mapping[str, Any]) -> list[str]:
    if not isinstance(mapping, Mapping):
        raise TypeError("Expected a mapping.")
    return sorted(mapping)


def _value(item: Any) -> Any:
    return getattr(item, "value", item)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _encode_json(value: Any) -> bytes:
    """Compact encoding, matching how ToolDispatcher and AgentLoop size output."""

    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
