"""The search_repo tool: retrieve ranked evidence chunks from the corpus.

Wraps a pre-built ``RetrievalPipeline`` rather than reshaping its own copy of
the corpus -- constructing one is Member 1/2's owned process (tag, chunk,
and BM25-index the whole corpus via ``tag_provenance.load_documents_from_register``
and ``build_retrieval_pipeline``), not something this tool should silently
redo. The pipeline is supplied once at construction, the same way
``ReadFileTool`` loads its allow-list once rather than per call.

Output is shaped here instead of via ``RetrievalResult.to_search_repo_output()``
because that method drops ``doc_type``, and ``rag.context_builder.build_context``
needs ``chunk.doc_type.value`` on every chunk to render its evidence tags.
Everything else mirrors ``to_search_repo_output()`` exactly (``text``,
``source_path``, optional ``requirement_id``).
"""

from __future__ import annotations

from typing import Any, Collection, Iterable, Mapping

from orchestrator import ToolRisk
from rag import RetrievalPipeline


class SearchRepoTool:
    """Read-only tool satisfying orchestrator.tool_dispatcher's Tool Protocol."""

    name = "search_repo"
    risk = ToolRisk.READ_ONLY

    def __init__(
        self,
        pipeline: RetrievalPipeline,
        *,
        allowed_roles: Iterable[str] = ("developer",),
    ) -> None:
        self.pipeline = pipeline
        self.allowed_roles: Collection[str] = tuple(allowed_roles)

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Require a non-empty ``query``; accept optional ``path_scope``/``top_k``."""

        if not isinstance(arguments, Mapping):
            raise ValueError("search_repo arguments must be an object.")

        allowed_keys = {"query", "path_scope", "top_k"}
        unknown = set(arguments) - allowed_keys
        if unknown:
            raise ValueError(f"search_repo received unknown argument(s): {sorted(unknown)}.")

        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("'query' must be a non-empty string.")
        validated: dict[str, Any] = {"query": query}

        path_scope = arguments.get("path_scope")
        if path_scope is not None and (
            not isinstance(path_scope, str) or not path_scope.strip()
        ):
            raise ValueError("'path_scope' must be a non-empty string or null.")
        validated["path_scope"] = path_scope

        top_k = arguments.get("top_k")
        if top_k is not None and (
            not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0
        ):
            raise ValueError("'top_k' must be a positive integer or null.")
        validated["top_k"] = top_k

        return validated

    def run(
        self,
        arguments: Mapping[str, Any],
        context: Any,
    ) -> Mapping[str, Any]:
        """Retrieve and shape chunks, preserving doc_type for the context builder."""

        result = self.pipeline.retrieve(
            arguments["query"],
            path_scope=arguments["path_scope"],
            top_k=arguments["top_k"],
        )

        chunks: list[dict[str, Any]] = []
        for retrieved in result.chunks:
            chunk = retrieved.chunk
            entry: dict[str, Any] = {
                "text": chunk.text,
                "source_path": chunk.source_path,
                "doc_type": chunk.doc_type.value,
            }
            if chunk.requirement_id:
                entry["requirement_id"] = chunk.requirement_id
            chunks.append(entry)

        return {"chunks": chunks, "not_in_corpus": result.not_in_corpus}

    def validate_output(self, output: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(output.get("not_in_corpus"), bool):
            raise ValueError("search_repo output must include a boolean 'not_in_corpus'.")

        chunks = output.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError("search_repo output must include a list of 'chunks'.")

        validated_chunks: list[dict[str, Any]] = []
        for entry in chunks:
            if not isinstance(entry, Mapping):
                raise ValueError("Every search_repo chunk must be an object.")
            text = entry.get("text")
            source_path = entry.get("source_path")
            doc_type = entry.get("doc_type")
            if not isinstance(text, str):
                raise ValueError("Every search_repo chunk must include 'text'.")
            if not isinstance(source_path, str) or not source_path:
                raise ValueError("Every search_repo chunk must include 'source_path'.")
            if not isinstance(doc_type, str) or not doc_type:
                raise ValueError("Every search_repo chunk must include 'doc_type'.")

            validated_entry: dict[str, Any] = {
                "text": text,
                "source_path": source_path,
                "doc_type": doc_type,
            }
            requirement_id = entry.get("requirement_id")
            if requirement_id is not None:
                if not isinstance(requirement_id, str) or not requirement_id:
                    raise ValueError(
                        "search_repo chunk 'requirement_id' must be a non-empty string."
                    )
                validated_entry["requirement_id"] = requirement_id
            validated_chunks.append(validated_entry)

        return {"chunks": validated_chunks, "not_in_corpus": output["not_in_corpus"]}
