#!/usr/bin/env python3
"""Run one real Week 2 model interaction for Member 2 evidence.

This is a development smoke runner, not the production configuration loader
owned by Member 5. It reads only the API-key variable named by --api-key-env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from models.client import ChatCompletionsClient, ModelIntegrationError
from rag.pipeline import ProposalInput, generate_test_proposals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one model-backed test-proposal interaction."
    )
    parser.add_argument("--endpoint", required=True, help="Full chat-completions URL")
    parser.add_argument("--model", required=True, help="Model ID selected by Member 3")
    parser.add_argument("--api-key-env", default="MODEL_API_KEY")
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--requirement-file", required=True, type=Path)
    parser.add_argument("--requirement-id")
    parser.add_argument("--source-file", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-tokens", type=int, default=1_200)
    parser.add_argument(
        "--no-json-mode",
        action="store_true",
        help="Do not send the OpenAI-compatible JSON response-format option",
    )
    return parser


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelIntegrationError(f"Could not read required file: {path}") from exc


def main() -> int:
    args = build_parser().parse_args()
    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        print(
            f"Integration failed: environment variable {args.api_key_env} is missing.",
            file=sys.stderr,
        )
        return 2

    try:
        client = ChatCompletionsClient(
            endpoint_url=args.endpoint,
            api_key=api_key,
            model=args.model,
            timeout_seconds=args.timeout,
            max_tokens=args.max_tokens,
            json_mode=not args.no_json_mode,
        )
        result = generate_test_proposals(
            proposal_input=ProposalInput(
                requirement_text=read_text(args.requirement_file),
                requirement_id=args.requirement_id,
                source_text=read_text(args.source_file),
                source_path=str(args.source_file),
            ),
            system_prompt=read_text(args.prompt_file),
            prompt_version=args.prompt_version,
            client=client,
        )
    except ModelIntegrationError as exc:
        print(f"Integration failed: {exc}", file=sys.stderr)
        return 2

    evidence = {
        "model": result.model,
        "prompt_version": result.prompt_version,
        "latency_ms": result.latency_ms,
        "request_id": result.request_id,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
        },
        "output": result.output,
    }
    print(json.dumps(evidence, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
