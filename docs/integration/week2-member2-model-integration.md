# Week 2 Member 2 Deliverable Guide

## Role and Deliverable

The Week 2 responsibility for Member 2 was to connect the application to the foundation model selected by Member 3. The completed deliverable is a working baseline model interaction and the supporting integration code required to operate it.

The implementation accepts an explicitly supplied software requirement and source file, sends them to the configured model with a versioned prompt, and returns structured test proposals. This establishes the smallest useful model-backed capability before later work adds retrieval, tools, sandboxed test execution, memory, and an agent loop.

The completed work includes a provider-neutral client, API adapter, integration pipeline, error handling, a real-model smoke runner, offline integration tests, and one synthetic smoke fixture. The offline test suite passes. The remaining evidence step is to run the integration against the selected model and prompt and record the sanitized result.

## AI Assistance and Responsibility

The integration work was supported by OpenAI Codex for planning, code generation, explanation, and validation. Claude Code was also used during independent review of the assignment and repository that informed the Week 2 plan. These contributions were recorded in the team AI Engineering Log in accordance with the assignment requirements.

Before submission, the implementation was reviewed, the test suite was executed, the live model response was inspected, and the API request, response parsing, error handling, and security decisions were evaluated. Final responsibility for the correctness and security of the submitted code remains with the contributor.

## Scope of Work

The completed scope includes:

- The provider-neutral model-client contract.
- The configured provider API adapter.
- The pipeline that connects the prompt, evidence, model call, and response parser.
- Integration-specific errors and failure handling.
- Offline tests for successful and failed integration paths.
- A smoke runner for demonstrating a real model interaction.
- The technical evidence for commit, pull request, and ClickUp task tracking.

The following work remains outside the scope of this deliverable:

| Work | Owner | How it is used |
| --- | --- | --- |
| Requirement and test-proposal domain models | Member 1 | The model response is passed to Member 1's parser or validator. |
| Model selection, Prompt Specification, prompt versions, and prompt loader | Member 3 | The selected prompt and version are sent to the configured model. |
| Ten prompt-evaluation cases, evaluation harness, and evaluation table | Member 4 | A stable pipeline function is exposed for the harness to call. |
| Production environment and configuration loader | Member 5 | The endpoint, API key, model name, and timeout are accepted from the production loader. |
| Week 2 progress report | Member 5 | Evidence and contribution summaries are included in the report. |

The smoke runner reads one named API-key environment variable to demonstrate the adapter before the production configuration loader is merged. It is not intended to replace Member 5's configuration work.

## Baseline Interaction

The implemented flow is:

```text
Requirement and source file
            |
            v
Prompt text and version supplied by Member 3
            |
            v
Member 2 integration pipeline
            |
            v
Provider-neutral model-client contract
            |
            v
Configured chat-completions API
            |
            v
Normalized model response and metadata
            |
            v
JSON parsing or Member 1's domain validator
            |
            v
Structured proposal result for Member 4
```

This Week 2 baseline does not search the repository automatically. The requirement and source file are supplied explicitly. In Week 3, the retrieval pipeline can replace the explicit input step without changing the model-client contract.

## Files Implemented

### `src/qa_agent/__init__.py`

This file defines the public surface of the `qa_agent` package. It re-exports the main model-client and pipeline types so other application modules can import them from one stable location.

It does not contain application logic. Its purpose is to make the integration package easier to use and to prevent other members from depending on internal file locations.

### `src/qa_agent/model_integration.py`

This file combines the provider-neutral types, integration errors, and HTTP adapter because they form one small integration unit. This reduces navigation and avoids several one-purpose files while keeping the pipeline separate.

The file defines these errors:

- `IntegrationInputError` for missing requirements, source code, prompt text, or prompt version.
- `ModelConfigurationError` for an invalid endpoint, API key, model name, timeout, or output-token limit.
- `ModelAuthenticationError` for rejected credentials.
- `ModelRateLimitError` for provider quota or rate-limit failures.
- `ModelTimeoutError` for requests that exceed the configured timeout.
- `ModelProviderError` for provider network failures or malformed API responses.
- `ModelResponseError` for model output that is not valid application JSON or fails Member 1's domain validation.

These categories allow the application to respond differently to configuration, provider, and model-output failures. Error messages do not include the API key.

`ModelClient` is a protocol with one `generate` method. Any provider adapter can implement this method. The pipeline therefore does not depend on whether the underlying provider is OpenAI-compatible or another service.

`ModelCallResult` normalizes the information returned by a provider:

- Raw assistant text.
- Actual model ID.
- Request latency.
- Token usage when reported.
- Provider request ID when reported.

`TokenUsage` stores input, output, and total token counts. This information can support the Model Selection Note and later evaluation without duplicating other team members' deliverables.

The same file contains the real HTTP integration. It implements `ChatCompletionsClient`, which calls a configured endpoint using the common OpenAI-compatible chat-completions request format.

The adapter:

- Validates the endpoint, model name, API key, timeout, and token limit.
- Sends system and user messages to the configured endpoint.
- Requests a JSON object when JSON mode is enabled.
- Measures request latency.
- Extracts assistant text, model ID, request ID, and token usage.
- Converts authentication, quota, timeout, HTTP, network, and malformed API failures into stable integration errors.
- Avoids including the API key in application errors.

The endpoint and model are configurable, so this adapter does not choose the team model. Member 3 retains that decision. If the selected provider does not support the chat-completions format, a second adapter can be added that implements the same `ModelClient` contract without changing the pipeline.

### `src/qa_agent/pipeline.py`

This file coordinates the baseline model interaction.

`ProposalInput` holds the explicit requirement text, requirement ID, source path, and source text. These are integration inputs rather than replacements for Member 1's domain models.

`build_user_content` serializes the requirement and source into JSON. It does not add prompt instructions because prompt wording belongs to Member 3.

`generate_test_proposals` performs the complete baseline flow:

1. It validates that the supplied evidence, prompt text, and prompt version are present.
2. It serializes the requirement and source.
3. It calls the supplied `ModelClient`.
4. It passes the raw model response to a response parser.
5. It returns the parsed output together with model, prompt, latency, token, and request metadata.

The default parser checks that the response is a valid JSON object. After Member 1's domain models are merged, the application can pass `ProposalSet.model_validate_json` as the parser. This enables Member 1's validation without duplicating their contribution.

### `scripts/member2_model_smoke.py`

This is the command-line smoke runner for a single real model interaction. It accepts:

- The chat-completions endpoint.
- The model ID selected by Member 3.
- The name of the API-key environment variable.
- Member 3's prompt file and version.
- A requirement file and optional requirement ID.
- A source file.
- Timeout and maximum output-token settings.

It calls the integration pipeline and prints a sanitized JSON result containing the model, prompt version, latency, request ID, token usage, and parsed output. It does not print the API key.

This script is development and evidence tooling. Member 5's production configuration loader will eventually construct the same client using the team application settings.

### `tests/integration/test_model_integration.py`

The pipeline and provider-adapter tests are combined in this file because both verify the same baseline interaction. The tests do not contact a paid model service. Pipeline tests use a fake client implementing the same `ModelClient` contract, while adapter tests replace the network call with a controlled fake response.

The tests verify that:

- The pipeline sends the prompt and serialized evidence to the client.
- Valid JSON is returned with the correct model and prompt metadata.
- A parser supplied by Member 1 can replace the default parser.
- Non-JSON output is rejected.
- A JSON array is rejected because the application expects an object.
- Empty requirements are rejected before a provider call occurs.

The adapter tests also verify that:

- A successful provider response is normalized correctly.
- The request contains the configured model and JSON response option.
- Token usage and request IDs are captured.
- Socket timeouts become `ModelTimeoutError`.
- HTTP 401 responses become `ModelAuthenticationError`.
- Authentication errors do not reveal the API key.
- A provider response without assistant text is rejected.

These tests verify the integration code and are not Member 4's formal ten-case prompt evaluation.

### `tests/fixtures/member2/login_requirement.txt`

This synthetic requirement is used only for the smoke run. It states how a sample authentication service should handle an incorrect password and an unavailable service.

It is not part of Member 4's ten-case evaluation set.

### `tests/fixtures/member2/login_service.py`

This small synthetic source file is paired with the authentication requirement. It gives the model concrete source code from which it can propose tests during the smoke run.

It is test input only. It is not part of the QA Agent implementation and does not represent another member's domain-model contribution.

### `docs/integration/week2-member2-model-integration.md`

This document serves as the deliverable guide for the integration work. It describes the architecture, file-level implementation, validation methods, real-run requirements, evidence collection, and handoff points to the rest of the team.

## Offline Test Execution

From the repository root, the offline verification command is:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests/integration -v
```

The current result is:

```text
Ran 9 tests
OK
```

The tests require no API key and make no network or paid provider calls.

## Information Required Before the Real Run

The following information is required from Member 3 before the live model interaction can be executed:

1. The selected provider.
2. The exact model ID.
3. The model's chat-completions endpoint.
4. The approved prompt file.
5. The prompt version.
6. Confirmation that the provider supports JSON response mode.

The agreed API-key environment variable and settings structure are required from Member 5. Member 1's production response parser is also required before final application-level validation can be demonstrated.

Access to Claude Code does not automatically grant application access to an Anthropic API key. API access must be verified separately.

## Real Baseline Interaction Procedure

The live key is entered without placing it directly in the shell command:

```bash
read -rsp "Model API key: " MODEL_API_KEY
export MODEL_API_KEY
```

The baseline interaction is then executed with:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 scripts/member2_model_smoke.py \
  --endpoint "CHOSEN_CHAT_COMPLETIONS_ENDPOINT" \
  --model "CHOSEN_MODEL_ID" \
  --prompt-file "prompts/CHOSEN_PROMPT_FILE" \
  --prompt-version "v1.0" \
  --requirement-id "REQ-AUTH-01" \
  --requirement-file "tests/fixtures/member2/login_requirement.txt" \
  --source-file "tests/fixtures/member2/login_service.py"
```

The `--no-json-mode` option is used only if Member 3 confirms that the selected endpoint does not accept the `response_format` option.

## Handoff to Member 1

After Member 1's models are available, the production parser is used as follows:

```python
result = generate_test_proposals(
    proposal_input=proposal_input,
    system_prompt=prompt.text,
    prompt_version=prompt.version,
    client=model_client,
    response_parser=ProposalSet.model_validate_json,
)
```

This integrates Member 1's domain validation without recreating their data models.

## Handoff to Member 3

The input contract used by the pipeline is provided to Member 3, and the selected provider is confirmed to support JSON mode. Member 3 supplies the prompt text and version, and the configured model receives both without modifying the prompt content.

When Member 3 produces a new prompt version, the calling application changes the supplied prompt text and version. The provider and pipeline code do not require modification.

## Handoff to Member 4

The `generate_test_proposals` function and a working call example are provided to Member 4. Member 4 invokes that function once for each of the ten evaluation cases.

The cases, expected outcomes, evaluation runner, scoring logic, and evaluation table are not authored as part of this deliverable. The returned `PipelineResult` provides the model, prompt version, latency, token usage, request ID, and parsed output required for recording.

## Handoff to Member 5

The following settings are required to construct the model client:

- Provider endpoint.
- Model ID.
- API key.
- Timeout.
- Maximum output tokens.
- JSON-mode setting.

Member 5 loads and validates these settings in the production configuration module. No competing environment loader is created as part of this work.

The contribution statement, commit, pull request, test output, real-run evidence, model ID, prompt version, and latency are also provided to Member 5 for the Week 2 progress report.

## Evidence Collection

The required evidence includes:

1. The successful offline integration test output.
2. One sanitized real model-interaction result.
3. A screenshot showing the command and result without the API key.
4. The exact model ID and prompt version used.
5. The measured request latency.
6. The authored commit SHA.
7. The pull-request URL.
8. The ClickUp task URL and final status.
9. The paths of the integration files implemented.

Raw responses containing confidential or restricted content are not committed. The Week 2 smoke fixture is synthetic.


