"""
Tests for the self-correcting creative learning loop (attribution + brains + holdout gate).
Runnable with plain python: `python3 tests/test_creative_learning.py`.

Uses a REAL throwaway SQLite DB through the app's own init_db()+migrations, so it also
exercises the additive-migration / fresh-create path (verify item 7).
"""
import os, sys, uuid, tempfile, json

# Boot config BEFORE importing app.* — SECRET_KEY is required, DB points at a temp file.
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-comfortably-long-enough-xx")
_DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import init_db, SessionLocal          # noqa: E402
from app.migrations import run_migrations               # noqa: E402
init_db()
run_migrations()   # idempotent upgrade-in-place must be clean on an already-created schema

from app.models.creative_team import CreativeDecision   # noqa: E402
from app.models.learning import LearningEvent, CreativeBrainRule  # noqa: E402
from app.services import learning_loop as learn          # noqa: E402
from app.services import feedback_attribution as fa       # noqa: E402
from app.services import creative_tuner as ct             # noqa: E402
from app.services.learning_service import is_holdout      # noqa: E402

_passed = 0
def check(name, cond):
    global _passed
    assert cond, f"FAIL: {name}"
    _passed += 1
    print(f"  ok: {name}")


def _id_in_bucket(holdout: bool) -> str:
    while True:
        i = str(uuid.uuid4())
        if is_holdout(i) is holdout:
            return i


def add(db, ref, vertical, voice="v1", char="c1", script="rewrite", cap="ffmpeg",
        capr="none", model=None, rid=None):
    d = CreativeDecision(id=(rid or str(uuid.uuid4())), request_id=str(uuid.uuid4()),
                         creative_ref=ref, vertical=vertical, voice_id=voice, character_key=char,
                         script_mode=script, caption_method=cap, caption_removal_method=capr,
                         video_model=model, lipsync_provider="sync")
    db.add(d); db.commit(); return d


db = SessionLocal()

# ── PURE attribution unit tests (no DB) ───────────────────────────────────────
check("attr: voice-only", fa.attribute("voice sounds too young") == ["voice_cast"])
check("attr: ambiguous → empty", fa.attribute("make it better") == [])
check("attr: empty text → empty", fa.attribute("") == [])
check("attr: script blame", "script_write" in fa.attribute("rewrite the hook, punchier copy"))
check("attr: donor caption → remove not place",
      fa.attribute("I still see the old caption/watermark") == ["caption_remove"])
check("attr: generic caption → place", fa.attribute("the subtitle timing is off") == ["caption_place"])
check("attr: only enum values", set(fa.attribute("mouth is out of sync and voice too old")).issubset(set(fa.BRAINS)))

# ── TEST 1: attribution is surgical — only the blamed brain takes the loss ─────
V = "t1"
add(db, "A", V, voice="v_young", char="c_A", script="rewrite", cap="ffmpeg")
learn.record_verdict(db, "A", "regenerated", "voice sounds too young")
rowA = db.query(CreativeDecision).filter_by(creative_ref="A").first()
check("t1: blamed_brains == ['voice_cast']", json.loads(rowA.blamed_brains) == ["voice_cast"])
check("t1: voice_cast label == LOSS", learn._brain_label(rowA, "voice_cast") == 0)
check("t1: footage_cast label == None (NOT penalized)", learn._brain_label(rowA, "footage_cast") is None)
check("t1: script_write label == None (NOT penalized)", learn._brain_label(rowA, "script_write") is None)
check("t1: caption_place label == None (NOT penalized)", learn._brain_label(rowA, "caption_place") is None)
check("t1: voice v_young ranked as loss", learn.voice_scores(db, V).get("v_young") == 0.0)
check("t1: character c_A NOT in ranking", "c_A" not in learn.character_scores(db, V))
check("t1: script 'rewrite' NOT in ranking", "rewrite" not in learn.script_scores(db, V))

# ── TEST 2: ambiguous verdict trains NO brain, only creative-level aggregate ──
V2 = "t2"
add(db, "B", V2, voice="v_b", char="c_B", script="verbatim")
learn.record_verdict(db, "B", "regenerated", "make it better")
rowB = db.query(CreativeDecision).filter_by(creative_ref="B").first()
check("t2: blamed_brains == [] (ambiguous)", json.loads(rowB.blamed_brains) == [])
check("t2: no brain trained (voice)", learn._brain_label(rowB, "voice_cast") is None)
check("t2: no brain trained (script)", learn._brain_label(rowB, "script_write") is None)
check("t2: voice_scores empty for vertical", learn.voice_scores(db, V2) == {})
agg = learn.creative_aggregate(db, V2)
check("t2: creative-level aggregate DID count it (n=1, loss)", agg["n"] == 1 and agg["wins"] == 0)

# ── TEST 3: 'accepted' is a win for EVERY brain ───────────────────────────────
V3 = "t3"
add(db, "C", V3, voice="v_c", char="c_C", script="from-scratch", cap="veed")
learn.record_verdict(db, "C", "accepted", "approved by buyer")
rowC = db.query(CreativeDecision).filter_by(creative_ref="C").first()
check("t3: voice win", learn._brain_label(rowC, "voice_cast") == 1)
check("t3: footage win", learn._brain_label(rowC, "footage_cast") == 1)
check("t3: script win", learn._brain_label(rowC, "script_write") == 1)
check("t3: caption win", learn._brain_label(rowC, "caption_place") == 1)

# ── TEST 4: ROI overrides the human verdict, holistically for ALL brains ──────
V4 = "t4"
add(db, "D", V4, voice="v_d", char="c_D")
learn.record_verdict(db, "D", "regenerated", "voice too young")   # blames voice only
learn.attach_roi(db, "D", 2.5)                                    # but it actually WON on platform
rowD = db.query(CreativeDecision).filter_by(creative_ref="D").first()
check("t4: ROI overrides verdict → voice WIN", learn._brain_label(rowD, "voice_cast") == 1)
check("t4: ROI holistic → footage WIN too", learn._brain_label(rowD, "footage_cast") == 1)
add(db, "E", V4, voice="v_e", char="c_E")
learn.attach_roi(db, "E", 0.2)                                    # ROI loss → all brains loss
rowE = db.query(CreativeDecision).filter_by(creative_ref="E").first()
check("t4: ROI loss → voice LOSS", learn._brain_label(rowE, "voice_cast") == 0)
check("t4: ROI loss → footage LOSS", learn._brain_label(rowE, "footage_cast") == 0)

# ── TEST 5: holdout gate REJECTS an overfit candidate (fits train, worse on holdout) ──
VG = "t5gate"
# 8 TRAIN wins for v_over (→ becomes 'preferred'), plus 4 HOLDOUT losses for the same voice.
for _ in range(8):
    d = add(db, f"g{uuid.uuid4().hex[:6]}", VG, voice="v_over", rid=_id_in_bucket(False))
    learn.attach_roi(db, d.creative_ref, 2.0)   # train wins
for _ in range(4):
    d = add(db, f"g{uuid.uuid4().hex[:6]}", VG, voice="v_over", rid=_id_in_bucket(True))
    learn.attach_roi(db, d.creative_ref, 0.1)   # holdout losses — the candidate will mispredict
before_events = db.query(LearningEvent).filter_by(brain="voice_cast", vertical=VG).count()
res = ct.tune_brain(db, "voice_cast", VG)
check("t5: candidate REJECTED (holdout did not improve)", res["improving"] is False)
check("t5: not promoted", res["promoted"] is False)
check("t5: no proposal raised (not improving)", res["proposal_created"] is False)
check("t5: a no-change LearningEvent was written",
      db.query(LearningEvent).filter_by(brain="voice_cast", vertical=VG).count() == before_events + 1)
check("t5: old (empty) rules kept — nothing to assert", ct.governed_scores(db, "voice_cast", VG) == {})

# ── TEST 6: COLD START — no data → empty scores, no governed rules, behavior unchanged ──
check("t6: voice_scores empty", learn.voice_scores(db, "coldstart") == {})
check("t6: script_scores empty", learn.script_scores(db, "coldstart") == {})
check("t6: caption_scores empty", learn.caption_scores(db, "coldstart") == {})
check("t6: governed_scores empty (no promoted rules)", ct.governed_scores(db, "voice_cast", "coldstart") == {})
check("t6: summary shape present + empty", learn.summary(db, "coldstart")["voices"] == {})

# ── TEST 8: 2 cycles over the bar → PROMOTE → creates a pending_admin PROPOSAL, NOT an active rule ──
# CHANGE 1: a promoted brain must NOT change engine behavior on its own — it only PROPOSES.
from app.models.learning import RuleProposal   # noqa: E402
V8 = "t8promote"
for _ in range(15):   # train: v_good wins, v_bad loses (>= MIN_N each)
    d = add(db, f"p{uuid.uuid4().hex[:6]}", V8, voice="v_good", rid=_id_in_bucket(False)); learn.attach_roi(db, d.creative_ref, 2.0)
    d = add(db, f"p{uuid.uuid4().hex[:6]}", V8, voice="v_bad", rid=_id_in_bucket(False)); learn.attach_roi(db, d.creative_ref, 0.1)
for _ in range(30):   # holdout: same signal generalizes (>= 50 holdout labels)
    d = add(db, f"p{uuid.uuid4().hex[:6]}", V8, voice="v_good", rid=_id_in_bucket(True)); learn.attach_roi(db, d.creative_ref, 2.0)
    d = add(db, f"p{uuid.uuid4().hex[:6]}", V8, voice="v_bad", rid=_id_in_bucket(True)); learn.attach_roi(db, d.creative_ref, 0.1)
c1 = ct.tune_brain(db, "voice_cast", V8)
check("t8: cycle1 improving (holdout agreement to ~1.0)", c1["improving"] is True and c1["holdout_agreement"] >= 0.85)
check("t8: cycle1 NOT promoted yet (needs 2 consecutive cycles)", c1["promoted"] is False)
check("t8: cycle1 raised NO proposal (not promoted)", c1["proposal_created"] is False)
check("t8: cycle1 engine read empty (no active rule)", ct.governed_scores(db, "voice_cast", V8) == {})
c2 = ct.tune_brain(db, "voice_cast", V8)
check("t8: cycle2 PROMOTED (>=0.85 over >=50 labels, 2 cycles)", c2["promoted"] is True)
check("t8: cycle2 created a pending_admin PROPOSAL", c2["proposal_created"] is True)
# THE key CHANGE-1 guarantee: promoted + proposal does NOT touch engine reads.
check("t8: promoted+proposal → engine read STILL empty (unapproved rule is inert)",
      ct.governed_scores(db, "voice_cast", V8) == {})
db.expire_all()
_prop8 = db.query(RuleProposal).filter_by(brain="voice_cast", vertical=V8, status="pending_admin").first()
check("t8: exactly one pending_admin proposal exists", _prop8 is not None)
check("t8: no CreativeBrainRule is active yet",
      db.query(CreativeBrainRule).filter_by(brain="voice_cast", vertical=V8, active=True).first() is None)
_ev8 = _prop8.detail_json
check("t8: bundle proposed_change prefers v_good", "v_good" in (_ev8["proposed_change"]["preferred"] or {}))
check("t8: bundle before/after agreement present", _ev8["reasoning"]["agreement_after"] >= 0.85)
check("t8: bundle has pattern_summary", bool(_ev8.get("pattern_summary")))

# ── TEST 9: approval flow WITH human feedback — evidence has trigger_creatives + feedback text ──
import asyncio  # noqa: E402
from app.routes import regen as regenroutes   # noqa: E402
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)

V9 = "t9approve"
for _ in range(10):   # train
    d = add(db, f"q{uuid.uuid4().hex[:6]}", V9, voice="v_win", rid=_id_in_bucket(False)); learn.record_verdict(db, d.creative_ref, "accepted", "buyer approved")
    d = add(db, f"q{uuid.uuid4().hex[:6]}", V9, voice="v_lose", rid=_id_in_bucket(False)); learn.record_verdict(db, d.creative_ref, "regenerated", "voice sounds too young")
for _ in range(30):   # holdout (>=50 labels)
    d = add(db, f"q{uuid.uuid4().hex[:6]}", V9, voice="v_win", rid=_id_in_bucket(True)); learn.record_verdict(db, d.creative_ref, "accepted", "buyer approved")
    d = add(db, f"q{uuid.uuid4().hex[:6]}", V9, voice="v_lose", rid=_id_in_bucket(True)); learn.record_verdict(db, d.creative_ref, "regenerated", "voice sounds too young")
ct.tune_brain(db, "voice_cast", V9)
r9 = ct.tune_brain(db, "voice_cast", V9)
check("t9: promoted with human labels", r9["promoted"] is True and r9["proposal_created"] is True)
db.expire_all()
_p9 = db.query(RuleProposal).filter_by(brain="voice_cast", vertical=V9, status="pending_admin").first()
_trig = (_p9.detail_json.get("trigger_creatives") or [])
check("t9: >=1 trigger creative with feedback text", any((t.get("feedback") or "") for t in _trig))
check("t9: engine read empty BEFORE approval", ct.governed_scores(db, "voice_cast", V9) == {})

# APPROVE via the real endpoint → rule becomes active, proposal applied, LearningEvent written
_before_events = db.query(LearningEvent).filter_by(brain="voice_cast", vertical=V9).count()
_resp = _run(regenroutes.learn_proposal_approve(_p9.id, {"approver": "tester"}))
check("t9: approve endpoint ok", _resp["success"] is True)
db.expire_all()
check("t9: AFTER approval engine read is biased (v_win present)",
      "v_win" in ct.governed_scores(db, "voice_cast", V9))
check("t9: governed_preference returns the approved value", ct.governed_preference(db, "voice_cast", V9) == "v_win")
_p9r = db.query(RuleProposal).filter_by(id=_p9.id).first()
check("t9: proposal marked applied + approver recorded", _p9r.status == "applied" and _p9r.reviewed_by == "tester")
check("t9: a LearningEvent was written on approval",
      db.query(LearningEvent).filter_by(brain="voice_cast", vertical=V9).count() == _before_events + 1)

# ── TEST 10: REJECT keeps old behavior (no rule activated) ──
V10 = "t10reject"
for _ in range(10):
    d = add(db, f"r{uuid.uuid4().hex[:6]}", V10, voice="v_w", rid=_id_in_bucket(False)); learn.record_verdict(db, d.creative_ref, "accepted", "ok")
    d = add(db, f"r{uuid.uuid4().hex[:6]}", V10, voice="v_l", rid=_id_in_bucket(False)); learn.record_verdict(db, d.creative_ref, "regenerated", "voice too old")
for _ in range(30):
    d = add(db, f"r{uuid.uuid4().hex[:6]}", V10, voice="v_w", rid=_id_in_bucket(True)); learn.record_verdict(db, d.creative_ref, "accepted", "ok")
    d = add(db, f"r{uuid.uuid4().hex[:6]}", V10, voice="v_l", rid=_id_in_bucket(True)); learn.record_verdict(db, d.creative_ref, "regenerated", "voice too old")
ct.tune_brain(db, "voice_cast", V10); ct.tune_brain(db, "voice_cast", V10)
db.expire_all()
_p10 = db.query(RuleProposal).filter_by(brain="voice_cast", vertical=V10, status="pending_admin").first()
_run(regenroutes.learn_proposal_reject(_p10.id, {"reason": "not convinced", "approver": "tester"}))
db.expire_all()
check("t10: proposal marked rejected", db.query(RuleProposal).filter_by(id=_p10.id).first().status == "rejected")
check("t10: engine read STILL empty after reject (old behavior kept)", ct.governed_scores(db, "voice_cast", V10) == {})

# ── TEST 11: a NON-promoted brain (too little holdout) produces NO pending proposal ──
V11 = "t11gathering"
for _ in range(10):   # improving but only a handful of holdout labels → never promotes
    d = add(db, f"s{uuid.uuid4().hex[:6]}", V11, script="rewrite", rid=_id_in_bucket(False)); learn.attach_roi(db, d.creative_ref, 2.0)
    d = add(db, f"s{uuid.uuid4().hex[:6]}", V11, script="from-scratch", rid=_id_in_bucket(False)); learn.attach_roi(db, d.creative_ref, 0.1)
for _ in range(2):
    d = add(db, f"s{uuid.uuid4().hex[:6]}", V11, script="rewrite", rid=_id_in_bucket(True)); learn.attach_roi(db, d.creative_ref, 2.0)
r11 = ct.tune_brain(db, "script_write", V11)
check("t11: not promoted (too few holdout labels)", r11["promoted"] is False)
check("t11: NO proposal (still gathering proof)", r11["proposal_created"] is False)
check("t11: no pending proposal row for this brain/vertical",
      db.query(RuleProposal).filter_by(brain="script_write", vertical=V11, status="pending_admin").first() is None)

# ── TEST 12: assert-wiring regression — with NO active rule every brain reads {} / None ──
for _brain in ("script_write", "caption_place", "caption_remove", "footage_cast"):
    check(f"t12: {_brain} governed_scores empty (no active rule)", ct.governed_scores(db, _brain, "nowhere") == {})
    check(f"t12: {_brain} governed_preference None (no active rule)", ct.governed_preference(db, _brain, "nowhere") is None)

# ── TEST 7: idempotent migrations + app import ────────────────────────────────
run_migrations()   # second run must not raise
check("t7: run_migrations idempotent", True)
import importlib
importlib.import_module("app.main")
check("t7: import app.main clean", True)

db.close()
print(f"\n{_passed} checks passed")
