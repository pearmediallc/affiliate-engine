"""
Per-user long-term agentic memory for the Studio LLM.

Short-term memory (the studio_messages thread) already exists in CL. This adds
LONG-term memory: stable preferences the user keeps choosing (factual) and what
they've asked for / made (episodic), scoped strictly by user_id so user A never
sees user B's memory. The Studio router uses it to personalize replies and
pre-fill the brief instead of re-asking what the user has historically always
chosen.

pgvector-optional by design. If the `vector` type is available (Postgres with
the extension enabled) embeddings are stored as vector(1536) and searched with
the `<=>` cosine operator; otherwise embeddings are stored as a JSON float array
in a TEXT column and cosine similarity is computed in Python over the user's
rows (per-user counts are small, so a scan is fine). The mode is detected once
at runtime from the actual embedding column type, so it always matches whatever
migrations created.

ANTI-HALLUCINATION: only real, user-stated facts are stored (each with a
verbatim `source_ref` for provenance); factual memories are overridable by
(user_id, mem_key) so there are no stale duplicates; retrieval returns nothing
below a similarity threshold rather than forcing an irrelevant fact.

Everything here is BEST-EFFORT: a memory failure never raises into the caller,
so chat/generation is never broken by this subsystem.
"""
import json
import math
import asyncio
import logging
from typing import Optional

from sqlalchemy import text

from ..config import settings
from ..database import engine

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"   # 1536 dims — matches the migration's vector(1536)

# Overridable factual/preference keys. Only these are stored (an arbitrary key from the LLM is
# dropped — anti-hallucination). Values are free text (e.g. cast_gender=male, preferred_seconds=20).
_ALLOWED_KEYS = (
    "usual_vertical", "cast_gender", "cast_age", "favorite_scene", "preferred_seconds",
    "favorite_copy_formula", "captions", "path", "tone", "brand", "state",
)
# Light normalization for the few keys the model tends to name differently. Keeps real facts we'd
# otherwise drop; anything still not in _ALLOWED_KEYS after this is discarded.
_KEY_SYNONYMS = {
    "vertical": "usual_vertical", "niche": "usual_vertical",
    "gender": "cast_gender", "sex": "cast_gender",
    "age": "cast_age", "age_band": "cast_age", "cast_age_band": "cast_age",
    "scene": "favorite_scene", "setting": "favorite_scene", "location": "favorite_scene",
    "seconds": "preferred_seconds", "length": "preferred_seconds", "duration": "preferred_seconds",
    "copy_formula": "favorite_copy_formula", "formula": "favorite_copy_formula",
    "geo": "state", "region": "state",
}

# vector-mode detection is cached: None = undetermined, True/False once known.
_VECTOR_MODE: Optional[bool] = None


# ── mode + math helpers ───────────────────────────────────────────────────────
def _vector_mode() -> bool:
    """True iff user_memory.embedding is a real pgvector column. Read from the actual column type
    (ground truth) so the service always agrees with whatever the migration created. Cached."""
    global _VECTOR_MODE
    if _VECTOR_MODE is not None:
        return _VECTOR_MODE
    mode = False
    try:
        if engine.dialect.name.startswith("postgres"):
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT udt_name FROM information_schema.columns "
                    "WHERE table_name = 'user_memory' AND column_name = 'embedding'"
                )).first()
                mode = bool(row and str(row[0]).lower() == "vector")
    except Exception:
        mode = False
    _VECTOR_MODE = mode
    return mode


def _vec_literal(emb: list) -> str:
    """pgvector text literal, e.g. '[0.1,0.2,...]' — Postgres casts this to `vector`."""
    return "[" + ",".join(f"{float(x):.7g}" for x in emb) + "]"


def _parse_emb(raw) -> Optional[list]:
    """Decode a fallback-mode embedding (JSON text) back to a float list."""
    if raw is None:
        return None
    try:
        val = json.loads(raw) if isinstance(raw, str) else raw
        return [float(x) for x in val] if isinstance(val, list) else None
    except Exception:
        return None


def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (na * nb)


async def _embed(text_in: str) -> Optional[list]:
    """Embed text via OpenAI text-embedding-3-small (sync client → thread). Best-effort → None."""
    if not settings.openai_api_key or not (text_in or "").strip():
        return None

    def _call():
        from openai import OpenAI
        oai = OpenAI(api_key=settings.openai_api_key)
        r = oai.embeddings.create(model=_EMBED_MODEL, input=text_in[:8000])
        return list(r.data[0].embedding)

    try:
        return await asyncio.to_thread(_call)
    except Exception as e:
        logger.warning(f"user_memory embed failed: {e}")
        return None


def _norm_key(raw) -> Optional[str]:
    if not raw:
        return None
    k = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    k = _KEY_SYNONYMS.get(k, k)
    return k if k in _ALLOWED_KEYS else None


# ── write path ────────────────────────────────────────────────────────────────
def _upsert(user_id: str, kind: str, mem_key: Optional[str], content: str,
            emb: Optional[list], source_ref: str) -> None:
    """Upsert one memory. Factual (mem_key set) overrides by (user_id, kind, mem_key); episodic
    (mem_key NULL) appends, because NULLs are distinct in the unique index on both SQLite + Postgres."""
    try:
        if _vector_mode() and emb is not None:
            emb_sql, emb_val = "CAST(:emb AS vector)", _vec_literal(emb)
        else:
            emb_sql, emb_val = ":emb", (json.dumps(emb) if emb is not None else None)
        sql = text(f"""
            INSERT INTO user_memory
                (user_id, kind, mem_key, content, embedding, source_ref, created_at, updated_at)
            VALUES
                (:uid, :kind, :mkey, :content, {emb_sql}, :src, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, kind, mem_key) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                source_ref = EXCLUDED.source_ref,
                updated_at = CURRENT_TIMESTAMP
        """)
        with engine.begin() as conn:
            conn.execute(sql, {"uid": user_id, "kind": kind, "mkey": mem_key,
                               "content": content, "emb": emb_val, "src": source_ref})
    except Exception as e:
        logger.warning(f"user_memory upsert failed ({kind}/{mem_key}): {e}")


def _transcript(recent_messages: list) -> str:
    lines = []
    for m in (recent_messages or [])[-12:]:
        role = (m.get("role") or "user")
        txt = (m.get("text") or "").replace("\n", " ").strip()[:400]
        if txt:
            lines.append(f"{role}: {txt}")
    return "\n".join(lines)


_EXTRACT_PROMPT = """You maintain a per-user long-term memory for a direct-response video Studio.
Read the recent conversation and extract ONLY what the user CLEARLY expressed — never guess, never
infer, never invent. If nothing qualifies, return empty arrays.

Return STRICT JSON:
{{
  "factual": [{{"key": "<one of the allowed keys>", "value": "<short value>", "source": "<verbatim phrase the user actually said>"}}],
  "episodic": [{{"summary": "<one sentence: what they asked for and/or made this turn>", "source": "<verbatim phrase>"}}]
}}

ALLOWED factual keys (use these EXACT keys, nothing else): {keys}
  - usual_vertical (e.g. home insurance, guns, sweeps), cast_gender (male|female),
    cast_age (under35|45-55|55plus or similar), favorite_scene (porch|kitchen|car|couch|office|walk),
    preferred_seconds (number), favorite_copy_formula, captions (on|off), path (scratch|avatar),
    tone, brand, state.

RULES (anti-hallucination):
- A factual item is only for a STABLE preference the user stated (a length they keep choosing, a cast
  they prefer, captions on/off, their vertical/state/brand). A one-off request is EPISODIC, not factual.
- Every item MUST include a `source` that is a verbatim phrase from the user's messages. No source → omit it.
- Do NOT restate the assistant's own actions as user facts. Only the user's stated intent counts.
- Keep values short. Prefer canonical values (male/female, on/off, scratch/avatar, a plain number for seconds).

CONVERSATION:
{transcript}
"""


async def extract(user_id, recent_messages: list) -> None:
    """One Gemini extraction → upsert factual (override) + append episodic, each embedded via OpenAI.
    Best-effort and non-blocking: never raises. Call fire-and-forget after producing a Studio reply."""
    user_id = str(user_id or "").strip()
    if not user_id or not recent_messages:
        return
    try:
        transcript = _transcript(recent_messages)
        if not transcript.strip():
            return
        from . import creative_team
        data = await creative_team._gemini_json(
            _EXTRACT_PROMPT.format(keys=", ".join(_ALLOWED_KEYS), transcript=transcript),
            temperature=0.1,
        )
        if not isinstance(data, dict):
            return
        for item in (data.get("factual") or []):
            if not isinstance(item, dict):
                continue
            key = _norm_key(item.get("key"))
            val = str(item.get("value") or "").strip()
            src = str(item.get("source") or "").strip()[:400]
            if not key or not val or not src:   # require provenance — no source, no store
                continue
            content = f"{key}: {val}"
            _upsert(user_id, "factual", key, content, await _embed(content), src)
        for item in (data.get("episodic") or []):
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "").strip()[:1000]
            src = str(item.get("source") or "").strip()[:400]
            if not summary or not src:
                continue
            _upsert(user_id, "episodic", None, summary, await _embed(summary), src)
    except Exception as e:
        logger.warning(f"user_memory.extract failed: {e}")


# ── read path ─────────────────────────────────────────────────────────────────
def _search_pgvector(user_id: str, q_emb: list, k: int) -> list:
    sql = text("""
        SELECT kind, mem_key, content, 1 - (embedding <=> CAST(:q AS vector)) AS sim
        FROM user_memory
        WHERE user_id = :uid AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"q": _vec_literal(q_emb), "uid": user_id, "k": k}).mappings().all()
    return [{"kind": r["kind"], "mem_key": r["mem_key"], "content": r["content"],
             "sim": float(r["sim"])} for r in rows]


def _search_python(user_id: str, q_emb: list, k: int) -> list:
    sql = text("SELECT kind, mem_key, content, embedding FROM user_memory "
               "WHERE user_id = :uid AND embedding IS NOT NULL")
    with engine.connect() as conn:
        rows = conn.execute(sql, {"uid": user_id}).mappings().all()
    scored = []
    for r in rows:
        emb = _parse_emb(r["embedding"])
        if not emb:
            continue
        scored.append({"kind": r["kind"], "mem_key": r["mem_key"], "content": r["content"],
                       "sim": _cosine(q_emb, emb)})
    scored.sort(key=lambda x: x["sim"], reverse=True)
    return scored[:k]


async def retrieve(user_id, query: str, k: int = 5, min_sim: float = 0.25) -> list:
    """Semantic search of THIS user's memories. Returns up to k {kind, mem_key, content} whose cosine
    similarity to `query` is >= min_sim (the threshold is the anti-hallucination gate: below it we
    return nothing rather than surfacing an irrelevant fact). Best-effort → [] on any failure."""
    user_id = str(user_id or "").strip()
    if not user_id or not (query or "").strip():
        return []
    try:
        q_emb = await _embed(query)
        if q_emb is None:
            return []
        rows = _search_pgvector(user_id, q_emb, k) if _vector_mode() else _search_python(user_id, q_emb, k)
        return [{"kind": r["kind"], "mem_key": r["mem_key"], "content": r["content"]}
                for r in rows if r["sim"] >= min_sim][:k]
    except Exception as e:
        logger.warning(f"user_memory.retrieve failed: {e}")
        return []


def preferences(user_id) -> dict:
    """Current factual key→value map for THIS user (for brief pre-fill). Best-effort → {}."""
    user_id = str(user_id or "").strip()
    if not user_id:
        return {}
    try:
        sql = text("SELECT mem_key, content FROM user_memory "
                   "WHERE user_id = :uid AND kind = 'factual' AND mem_key IS NOT NULL "
                   "ORDER BY updated_at DESC")
        with engine.connect() as conn:
            rows = conn.execute(sql, {"uid": user_id}).mappings().all()
        out = {}
        for r in rows:
            key = r["mem_key"]
            if not key or key in out:
                continue
            val = r["content"] or ""
            if isinstance(val, str) and val.startswith(f"{key}:"):
                val = val[len(key) + 1:].strip()   # recover the value from stored "key: value"
            out[key] = val
        return out
    except Exception as e:
        logger.warning(f"user_memory.preferences failed: {e}")
        return {}


def render_context_block(mems: list, prefs: dict) -> str:
    """Compact prompt block of what we know about the user. Empty string when we know nothing."""
    if not mems and not prefs:
        return ""
    lines = ["WHAT WE KNOW ABOUT THIS USER (use to personalize + pre-fill the brief; do NOT re-ask "
             "what's already known here):"]
    for k, v in (prefs or {}).items():
        if v:
            lines.append(f"- {k}: {v}")
    episodic = [m.get("content") for m in (mems or [])
                if m.get("kind") in ("episodic", "semantic") and m.get("content")]
    if episodic:
        lines.append("Relevant past activity:")
        for c in episodic[:5]:
            lines.append(f"- {c}")
    return "\n".join(lines) + "\n\n"
