"""Pre-dispatch citation validation (Week 4 deliverable, Member 1).

Member 2's tool-calling boundary (src/orchestrator/router.py)
deliberately does not check citations itself. Its Week 4 report
(docs/integration/Week4_Member2_ToolCallingOrchestration.docx, Table 1 and
Section 6.3) lists this as a Member 1 handoff:

    Citation validation | Member 1 | Caller must validate before
    dispatch().

and the same report's open items for the team ask Member 1 to "confirm
citation validation occurs before dispatch()". This module is that check.

It enforces US-8's negative case ("A proposal without a traceable
reference to a requirement or code path is rejected automatically rather
than passed through with a missing citation") at the orchestration
boundary, for every action the model can propose, not only propose_test.
propose_action v1.1's OUTPUT FORMAT
(docs/prompts/propose_action/v1.1.md) requires an "evidence" field on
every response, so a proposal with no evidence, or one that cites a
source_path never actually supplied this turn, is rejected here, before
ToolDispatcher.dispatch() or dispatch_raw() is ever called.

This reuses UntraceableProposalError from models.types rather than
defining a second exception for the same failure, and generalises the
rule TestProposal.validate_sources already enforces for propose_test
outputs (Week 2) so it also covers search_repo, read_file, run_tests and
draft_issue proposals, which carry citations through ProposalSet.evidence
directly rather than through a TestProposal.

Week 5 adds one narrow exception for the agent loop (src/agent/loop.py).
propose_action v1.1's FAILURE BEHAVIOR tells the model to return
"no_action" instead of fabricating a citation when the context holds no
usable source. When retrieval has deterministically decided the query is
not in the corpus, the context contains no source_path at all, so the only
honest response the prompt allows is an evidence-free no_action. Rejecting
that response would punish the model for following its instructions.
The exception is therefore limited to Action.NO_ACTION, only applies when
the caller passes ``confirmed_not_in_corpus=True`` (a deterministic
retrieval result, never the model's own claim), and only when
``allowed_source_paths`` is empty. Every other evidence-free proposal, and
every fabricated citation for any action, is still rejected.
"""

from __future__ import annotations

from typing import Collection

from models.types import Action, ProposalSet, UntraceableProposalError


def validate_citations(
    proposal: ProposalSet,
    allowed_source_paths: Collection[str],
    *,
    confirmed_not_in_corpus: bool = False,
) -> ProposalSet:
    """Reject ``proposal`` if it has no evidence, or cites a source_path
    that was not actually supplied to the model this turn.

    Call this on every ``ProposalSet`` before it reaches
    ``ToolDispatcher.dispatch()``:

        proposal = validate_citations(proposal, allowed_source_paths)
        result = dispatcher.dispatch(proposal, context=context)

    ``allowed_source_paths`` should be exactly the set of source paths the
    model was actually given this turn (for example, the source paths of
    the retrieved chunks placed in the context bundle). Passing a wider
    set than that defeats the check.

    Narrow no-evidence exception: an evidence-free ``Action.NO_ACTION``
    proposal is accepted only when ``confirmed_not_in_corpus`` is exactly
    ``True`` and ``allowed_source_paths`` is empty. This mirrors
    propose_action v1.1's FAILURE BEHAVIOR, which requires "no_action"
    rather than a fabricated citation when the corpus has no evidence. The
    flag must come from deterministic retrieval (for example
    ``AssembledContext.not_in_corpus``), never from the model's output. An
    evidence-free proposal for any other action is still rejected, and so
    is a no_action proposal that cites anything, since no citation can be
    traceable when nothing was supplied.

    Args:
        proposal: The structurally validated propose_action response to
            check.
        allowed_source_paths: The source paths that were genuinely
            supplied to the model this turn.
        confirmed_not_in_corpus: Set to ``True`` only when deterministic
            retrieval has confirmed the corpus holds no evidence for this
            turn. Defaults to ``False``, which keeps the original rule that
            every proposal needs evidence.

    Returns:
        The same ``proposal``, unchanged, when every evidence entry is
        traceable, or when the narrow no-evidence exception applies.
        Nothing is mutated or copied; this function either returns the
        input or raises.

    Raises:
        UntraceableProposalError: ``proposal.evidence`` is empty and the
            narrow no-evidence exception does not apply, or at least one
            evidence entry cites a ``source_path`` outside
            ``allowed_source_paths`` (US-8's negative case: a fabricated
            or missing citation).
    """
    allowed = set(allowed_source_paths)

    if not proposal.evidence:
        # The only evidence-free proposal that may pass: an honest
        # no_action after deterministic retrieval found nothing to cite.
        # ``is True`` keeps a truthy non-bool from opening the exception.
        if (
            confirmed_not_in_corpus is True
            and not allowed
            and proposal.action is Action.NO_ACTION
        ):
            return proposal
        raise UntraceableProposalError(
            f"Proposal for action {proposal.action.value!r} has no "
            "evidence and must be rejected before dispatch, not passed "
            "through with a missing citation."
        )

    for ref in proposal.evidence:
        if ref.source_path not in allowed:
            raise UntraceableProposalError(
                f"Proposal for action {proposal.action.value!r} cites "
                f"{ref.source_path!r}, which was not provided in this "
                "turn's context (fabricated citation)."
            )

    return proposal
