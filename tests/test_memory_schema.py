"""Tests for src/memory/schema.py (Member 1, Week 6)."""

from __future__ import annotations

import dataclasses
import json
import unittest
from datetime import datetime, timedelta, timezone

from memory import (
    MAX_TITLE_CHARS,
    MEMORY_DESCRIPTION,
    ProposalMemoryRecord,
    make_proposal_key,
    normalize_module,
    normalize_text,
)
from models.types import (
    Confidence,
    EvidenceRef,
    ProposalMemoryStatus,
    TestProposal,
)

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)
MODULE = "src/billing/discounts.py"
TITLE = "Lock account after five failures"


def proposed(**overrides) -> ProposalMemoryRecord:
    values = dict(module=MODULE, title=TITLE, proposed_at=T0, requirement_id="REQ-AUTH-3")
    values.update(overrides)
    return ProposalMemoryRecord.propose(**values)


class DescriptionTests(unittest.TestCase):
    def test_description_is_one_sentence_with_every_promise(self) -> None:
        text = MEMORY_DESCRIPTION
        self.assertEqual(text.count(". "), 0)
        self.assertTrue(text.endswith("."))
        for phrase in (
            "for each repository module",
            "which tests it has proposed",
            "which of those were run",
            "which a human explicitly rejected",
            "never repeats a proposal a developer has already seen or declined",
            "does not remember or reuse past diagnoses",
        ):
            self.assertIn(phrase, text)

    def test_record_holds_only_what_the_description_promises(self) -> None:
        # If this fails, a field was added. Check it against
        # MEMORY_DESCRIPTION before changing the expected set: the record must
        # never gain room for diagnoses, outputs, evidence text or notes.
        names = {f.name for f in dataclasses.fields(ProposalMemoryRecord)}
        self.assertEqual(
            names,
            {
                "module",
                "proposal_key",
                "title",
                "requirement_id",
                "target",
                "status",
                "proposed_at",
                "run_at",
                "test_node_id",
                "rejected_at",
                "rejected_by",
            },
        )


class NormalizeModuleTests(unittest.TestCase):
    def test_spellings_of_one_path_become_one(self) -> None:
        for raw in (
            "src/billing/discounts.py",
            "./src/billing/discounts.py",
            "src\\billing\\discounts.py",
            "src//billing/discounts.py",
            "  src/billing/discounts.py  ",
            "src/billing/./discounts.py",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_module(raw), "src/billing/discounts.py")

    def test_trailing_slash_is_dropped_and_case_is_kept(self) -> None:
        self.assertEqual(normalize_module("Src/Billing/"), "Src/Billing")

    def test_bad_modules_are_rejected(self) -> None:
        for bad in ("", "   ", ".", "./", "/etc/passwd", "C:\\repo\\x.py", "../x.py", "a/../b", None, 7):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_module(bad)  # type: ignore[arg-type]


class ProposalKeyTests(unittest.TestCase):
    def key(self, **overrides) -> str:
        values = dict(title=TITLE, requirement_id="REQ-AUTH-3", target=None)
        values.update(overrides)
        return make_proposal_key(MODULE, **values)

    def test_case_punctuation_and_spacing_do_not_change_the_key(self) -> None:
        base = self.key()
        for variant in (
            "lock account after five failures",
            "LOCK ACCOUNT AFTER FIVE FAILURES",
            "Lock account, after five failures.",
            "  Lock   account\tafter five   failures  ",
        ):
            with self.subTest(variant=variant):
                self.assertEqual(self.key(title=variant), base)

    def test_a_real_paraphrase_is_not_caught(self) -> None:
        # Recorded limitation, see the schema docstring: this is why the
        # prompt also shows the model its earlier proposals.
        self.assertNotEqual(self.key(title="Account locks after 5 failed logins"), self.key())

    def test_different_module_anchor_or_title_changes_the_key(self) -> None:
        base = self.key()
        self.assertNotEqual(make_proposal_key("src/other.py", title=TITLE, requirement_id="REQ-AUTH-3"), base)
        self.assertNotEqual(self.key(requirement_id="REQ-AUTH-4"), base)
        self.assertNotEqual(self.key(title="Unlock account after timeout"), base)

    def test_anchor_falls_back_from_requirement_to_target_to_nothing(self) -> None:
        with_target = make_proposal_key(MODULE, title=TITLE, target="apply_discount")
        with_requirement = make_proposal_key(MODULE, title=TITLE, requirement_id="apply_discount")
        bare = make_proposal_key(MODULE, title=TITLE)
        self.assertEqual(with_target, with_requirement)
        self.assertNotEqual(with_target, bare)
        # The requirement ID wins when both are present.
        both = make_proposal_key(MODULE, title=TITLE, requirement_id="REQ-1", target="apply_discount")
        only_requirement = make_proposal_key(MODULE, title=TITLE, requirement_id="REQ-1")
        self.assertEqual(both, only_requirement)

    def test_key_is_stable_and_module_spelling_independent(self) -> None:
        self.assertEqual(self.key(), self.key())
        self.assertEqual(
            make_proposal_key("./src\\billing/discounts.py", title=TITLE, requirement_id="REQ-AUTH-3"),
            self.key(),
        )

    def test_blank_title_is_rejected(self) -> None:
        for bad in ("", "   ", "!!!", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make_proposal_key(MODULE, title=bad)  # type: ignore[arg-type]


class RecordConstructionTests(unittest.TestCase):
    def test_propose_builds_a_valid_proposed_record(self) -> None:
        record = proposed(module=".\\src\\billing\\discounts.py")
        self.assertEqual(record.module, MODULE)
        self.assertIs(record.status, ProposalMemoryStatus.PROPOSED)
        self.assertEqual(record.proposed_at, T0)
        self.assertIsNone(record.run_at)
        self.assertIsNone(record.rejected_by)
        self.assertEqual(record.proposal_key, make_proposal_key(MODULE, title=TITLE, requirement_id="REQ-AUTH-3"))

    def test_from_test_proposal_uses_the_real_proposal_type(self) -> None:
        proposal = TestProposal(
            title=TITLE,
            target="apply_discount",
            rationale="Grounded in the supplied context.",
            evidence=(EvidenceRef(source_path="docs/auth.md"),),
            confidence=Confidence.HIGH,
            requirement_id="REQ-AUTH-3",
        )
        record = ProposalMemoryRecord.from_test_proposal(module=MODULE, proposal=proposal, proposed_at=T0)
        self.assertEqual(record.title, TITLE)
        self.assertEqual(record.target, "apply_discount")
        self.assertEqual(record.requirement_id, "REQ-AUTH-3")
        # Rationale and evidence are deliberately not remembered.
        self.assertFalse(hasattr(record, "rationale"))
        self.assertFalse(hasattr(record, "evidence"))
        with self.assertRaises(TypeError):
            ProposalMemoryRecord.from_test_proposal(module=MODULE, proposal={"title": "x"}, proposed_at=T0)  # type: ignore[arg-type]

    def test_record_is_frozen(self) -> None:
        record = proposed()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.title = "changed"  # type: ignore[misc]

    def test_direct_construction_checks_the_key_and_the_module(self) -> None:
        good = proposed()
        with self.assertRaises(ValueError):
            dataclasses.replace(good, proposal_key="0" * 16)
        with self.assertRaises(ValueError):
            dataclasses.replace(good, module="./src/billing/discounts.py")

    def test_naive_times_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            proposed(proposed_at=datetime(2026, 10, 7, 9, 0))

    def test_title_limits(self) -> None:
        with self.assertRaises(ValueError):
            proposed(title="x" * (MAX_TITLE_CHARS + 1))
        self.assertEqual(len(proposed(title="x" * MAX_TITLE_CHARS).title), MAX_TITLE_CHARS)

    def test_blank_or_padded_optional_text_is_rejected(self) -> None:
        for field in ("requirement_id", "target"):
            for bad in ("", "   ", " padded "):
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    proposed(**{field: bad})


class TransitionTests(unittest.TestCase):
    def test_proposed_to_run(self) -> None:
        run = proposed().mark_run(at=T1, test_node_id="tests/test_discounts.py::test_lockout")
        self.assertIs(run.status, ProposalMemoryStatus.RUN)
        self.assertEqual(run.run_at, T1)
        self.assertEqual(run.test_node_id, "tests/test_discounts.py::test_lockout")

    def test_run_without_a_node_id_is_allowed(self) -> None:
        self.assertIsNone(proposed().mark_run(at=T1).test_node_id)

    def test_proposed_to_rejected(self) -> None:
        rejected = proposed().mark_rejected(by="reviewer-1", at=T1)
        self.assertIs(rejected.status, ProposalMemoryStatus.REJECTED_BY_HUMAN)
        self.assertEqual((rejected.rejected_by, rejected.rejected_at), ("reviewer-1", T1))
        self.assertIsNone(rejected.run_at)

    def test_run_then_rejected_keeps_the_run_history(self) -> None:
        rejected = proposed().mark_run(at=T1).mark_rejected(by="reviewer-1", at=T2)
        self.assertIs(rejected.status, ProposalMemoryStatus.REJECTED_BY_HUMAN)
        self.assertEqual(rejected.run_at, T1)
        self.assertEqual(rejected.rejected_at, T2)

    def test_invalid_moves_raise(self) -> None:
        run = proposed().mark_run(at=T1)
        rejected = proposed().mark_rejected(by="reviewer-1", at=T1)
        with self.assertRaises(ValueError):
            run.mark_run(at=T2)
        with self.assertRaises(ValueError):
            rejected.mark_run(at=T2)
        with self.assertRaises(ValueError):
            rejected.mark_rejected(by="reviewer-2", at=T2)

    def test_a_move_never_changes_the_original(self) -> None:
        original = proposed()
        original.mark_run(at=T1)
        self.assertIs(original.status, ProposalMemoryStatus.PROPOSED)
        self.assertIsNone(original.run_at)

    def test_times_must_not_go_backwards(self) -> None:
        with self.assertRaises(ValueError):
            proposed().mark_run(at=T0 - timedelta(seconds=1))
        with self.assertRaises(ValueError):
            proposed().mark_run(at=T2).mark_rejected(by="reviewer-1", at=T1)

    def test_rejection_needs_a_named_human(self) -> None:
        for bad in ("", "   "):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                proposed().mark_rejected(by=bad, at=T1)

    def test_status_must_agree_with_the_fields(self) -> None:
        good = proposed()
        with self.assertRaises(ValueError):
            dataclasses.replace(good, run_at=T1)  # PROPOSED but has run_at
        with self.assertRaises(ValueError):
            dataclasses.replace(good, status=ProposalMemoryStatus.RUN)  # RUN without run_at
        with self.assertRaises(ValueError):
            dataclasses.replace(good, status=ProposalMemoryStatus.REJECTED_BY_HUMAN)
        with self.assertRaises(ValueError):
            dataclasses.replace(good, test_node_id="tests/x.py::t")  # node id without run_at


class SerialisationTests(unittest.TestCase):
    def test_every_stage_round_trips_through_json(self) -> None:
        stages = (
            proposed(),
            proposed(requirement_id=None, target="apply_discount").mark_run(at=T1, test_node_id="tests/a.py::t"),
            proposed().mark_run(at=T1).mark_rejected(by="reviewer-1", at=T2),
            proposed().mark_rejected(by="reviewer-1", at=T1),
        )
        for record in stages:
            with self.subTest(status=record.status):
                restored = ProposalMemoryRecord.from_dict(json.loads(json.dumps(record.to_dict())))
                self.assertEqual(restored, record)

    def test_from_dict_rejects_unknown_and_missing_fields(self) -> None:
        data = proposed().to_dict()
        with self.assertRaises(ValueError):
            ProposalMemoryRecord.from_dict({**data, "diagnosis": "off by one"})
        broken = dict(data)
        del broken["status"]
        with self.assertRaises(ValueError):
            ProposalMemoryRecord.from_dict(broken)
        with self.assertRaises(ValueError):
            ProposalMemoryRecord.from_dict([data])  # type: ignore[arg-type]

    def test_from_dict_revalidates_everything(self) -> None:
        data = proposed().to_dict()
        for field, bad in (
            ("status", "approved"),
            ("proposed_at", "yesterday"),
            ("proposed_at", 12345),
            ("proposed_at", "2026-10-07T09:00:00"),  # naive
            ("proposal_key", "tampered"),
            ("module", "../escape.py"),
        ):
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                ProposalMemoryRecord.from_dict({**data, field: bad})

    def test_to_dict_is_json_safe_and_uses_plain_values(self) -> None:
        data = proposed().mark_run(at=T1).to_dict()
        self.assertEqual(data["status"], "run")
        self.assertEqual(data["run_at"], T1.isoformat())
        json.dumps(data)


if __name__ == "__main__":
    unittest.main()
