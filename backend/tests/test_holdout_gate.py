"""
Tests for the holdout-gated tuning loop (Karpathy-loop verifier) in learning_service.

Runnable with plain python: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(64))") python3 tests/test_holdout_gate.py`

The critical case: a candidate rule set that perfectly fits TRAIN but does WORSE on
the HOLDOUT must be REJECTED (old rules kept) and must still write a no-change
LearningEvent. This is the leakage guard the whole loop is judged by.
"""
import os, sys, uuid, types, tempfile

os.environ.setdefault("SECRET_KEY", "x" * 80)
# A dedicated throwaway sqlite file so we never touch the dev DB.
_DBFILE = os.path.join(tempfile.gettempdir(), f"holdout_gate_test_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DBFILE}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models  # noqa: E402,F401  (register all tables)
from app.models.learning import LearningRecord, VerticalKnowledge, LearningEvent  # noqa: E402
from app.services import learning_service as ls  # noqa: E402

Base.metadata.create_all(bind=engine)

_passed = 0
def check(name, cond):
    global _passed
    assert cond, f"FAIL: {name}"
    _passed += 1
    print(f"  ok: {name}")


def _rec(rating, issues):
    return LearningRecord(
        id=str(uuid.uuid4()), vertical="v", feature="image_generation",
        input_data={}, feedback_rating=rating, feedback_issues=issues,
    )


def _rules(text):
    return {"prompt_rules": [{"rule": text, "confidence": 0.9, "evidence_count": 5}]}


# HOLDOUT reality: negatives are caused by "washed_out". The OLD (production) rules
# already capture that. A candidate mined from a TRAIN slice where "blurry" dominated
# fits train but does NOT generalize to this holdout.
HOLDOUT = [_rec("positive", []) for _ in range(5)] + [_rec("negative", ["washed_out"]) for _ in range(5)]
OLD_RULES = _rules("Avoid: washed_out colors")
CANDIDATE_LEAKY = _rules("Avoid: blurry subject")   # perfect on train, worse on holdout


def test_agreement_math():
    check("old rules generalize to holdout", ls.agreement(OLD_RULES, HOLDOUT) == 1.0)
    check("leaky candidate is worse on holdout", ls.agreement(CANDIDATE_LEAKY, HOLDOUT) == 0.5)
    check("empty rules == positive baseline", ls.agreement({}, HOLDOUT) == 0.5)


def test_split_deterministic():
    rid = str(uuid.uuid4())
    check("holdout split is reproducible", ls.is_holdout(rid) == ls.is_holdout(rid))


def test_gate_rejects_leakage():
    """The whole point: leaky candidate rejected, old rules kept, no-change event written."""
    db = SessionLocal()
    try:
        # Seed production knowledge with the GOOD (old) rules.
        db.add(VerticalKnowledge(id=str(uuid.uuid4()), vertical="v", learned_rules=OLD_RULES))
        db.commit()

        result = ls._apply_candidate(
            db=db, vertical="v", candidate_rules=CANDIDATE_LEAKY,
            holdout_records=HOLDOUT, total_samples=40, satisfaction=0.5,
        )

        check("gate rejected the leaky candidate", result["kept"] is False)
        check("persisted agreement is the HOLDOUT number", result["holdout_agreement"] == 1.0)
        check("before/after are holdout numbers (1.0 -> 0.5)",
              result["agreement_before"] == 1.0 and result["agreement_after"] == 0.5)

        kn = db.query(VerticalKnowledge).filter(VerticalKnowledge.vertical == "v").first()
        check("old rules left untouched (rollback)",
              kn.learned_rules["prompt_rules"][0]["rule"] == "Avoid: washed_out colors")

        events = db.query(LearningEvent).filter(LearningEvent.vertical == "v").all()
        check("exactly one LearningEvent written", len(events) == 1)
        check("event records the no-change decision", events[0].detail_json["kept"] is False)
        check("event agreement is holdout before/after",
              events[0].agreement_before == 1.0 and events[0].agreement_after == 0.5)
        check("not promoted (holdout too small / unstable)", result["promoted"] is False)
    finally:
        db.close()


def test_gate_keeps_real_improvement():
    """A candidate that genuinely beats the (empty) production rules on holdout is kept."""
    db = SessionLocal()
    try:
        result = ls._apply_candidate(
            db=db, vertical="v2", candidate_rules=OLD_RULES,   # covers washed_out -> 1.0
            holdout_records=HOLDOUT, total_samples=40, satisfaction=0.5,
        )
        check("gate kept the improving candidate", result["kept"] is True)
        check("kept agreement is the holdout number (1.0)", result["holdout_agreement"] == 1.0)
        kn = db.query(VerticalKnowledge).filter(VerticalKnowledge.vertical == "v2").first()
        check("candidate rules now live", kn.learned_rules["prompt_rules"][0]["rule"] == "Avoid: washed_out colors")
        n_events = db.query(LearningEvent).filter(LearningEvent.vertical == "v2").count()
        check("one LearningEvent written on keep", n_events == 1)
    finally:
        db.close()


if __name__ == "__main__":
    test_agreement_math()
    test_split_deterministic()
    test_gate_rejects_leakage()
    test_gate_keeps_real_improvement()
    print(f"\n{_passed} checks passed")
    try:
        os.remove(_DBFILE)
    except OSError:
        pass
