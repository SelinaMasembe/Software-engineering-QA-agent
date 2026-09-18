#!/usr/bin/env python3
"""Run one real model interaction using validated environment configuration.

The model endpoint, API key, model name, timeout, token limit, and JSON-mode
setting are loaded through the Member 5 configuration loader.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from models.client import ModelIntegrationError
from rag.pipeline import ProposalInput, generate_test_proposals
from config import build_model_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one model-backed test-proposal interaction."
    )
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--requirement-file", required=True, type=Path)
    parser.add_argument("--requirement-id")
    parser.add_argument("--source-file", required=True, type=Path)
    return parser


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelIntegrationError(f"Could not read required file: {path}") from exc


def main() -> int:
    args = build_parser().parse_args()

    try:
        client = build_model_client()

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
