"""
LLM-as-judge clip ranker — score gathered clips by predicted short-form "pop" potential using
only the metadata we already have (title, creator, views, duration). No extra downloads, so it's
cheap and cloud-safe: we judge candidates BEFORE spending a download/produce on one.

Why: OpusClip's production data shows an LLM judge's score band predicts whether a clip actually
gets used — export rate climbs steadily from ~13% (lowest score band) to ~35% (highest). We follow
their best practice of categorical integer scoring (1-5 per dimension) rather than float scores,
which drift. The caller blends these scores UNDER the creator-priority order, so the judge only
reorders clips within a tier — it never demotes a higher-priority creator.

Best-effort: any failure (no key, network, quota, bad output) returns an empty score map so the
caller falls back to the existing order. It can never break a run.
"""
from __future__ import annotations

from .config import env
from .sources import Clip

_TOOL = {
    "name": "rank_clips",
    "description": "Score candidate clips for a YouTube Shorts clips channel by how likely each is "
                   "to hook a viewer in the first second and get shared.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "description": "One entry per clip index shown. Include EVERY index exactly once.",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "The clip's [index] from the list."},
                        "hook": {"type": "integer",
                                 "description": "1-5: would the first second stop a scroll?"},
                        "clarity": {"type": "integer",
                                    "description": "1-5: self-contained / understandable without stream context?"},
                        "shareable": {"type": "integer",
                                      "description": "1-5: funny/shocking/relatable enough to share?"},
                    },
                    "required": ["index", "hook", "clarity", "shareable"],
                },
            }
        },
        "required": ["scores"],
    },
}


def score_clips(clips: list[Clip], llm_cfg: dict, top_k: int = 12) -> dict[str, float]:
    """Return {clip.id: total_score 3-15} for the first `top_k` clips. {} on any failure."""
    key = env("ANTHROPIC_API_KEY")
    if not clips or not key:
        return {}
    head = clips[:top_k]
    lines = []
    for i, c in enumerate(head):
        vc = f"{c.view_count:,} views" if c.view_count else "views n/a"
        dur = f"{round(c.duration)}s" if c.duration else "len n/a"
        lines.append(f"[{i}] {c.creator or '?'} · {c.source} · {vc} · {dur} · {c.title!r}")
    prompt = (
        "Pick which clip to post as a YouTube Short. Score EACH candidate below 1-5 on:\n"
        "  hook — does the first second stop a scroll?\n"
        "  clarity — is it self-contained and understandable without the stream's context?\n"
        "  shareable — is it funny/shocking/relatable enough that someone sends it to a friend?\n"
        "First infer each clip's TYPE from its title and weigh accordingly: a reaction / funny "
        "moment / fail / IRL-chaos clip can win on the visual alone, but a 'just chatting' or "
        "talking-head clip needs an unusually strong verbal hook to score well on hook & clarity. "
        "Favor titles that promise a clear payoff and clips with strong views relative to peers; "
        "penalize vague titles and inside-baseline stream chatter.\n\n" + "\n".join(lines)
    )
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=llm_cfg["model"],
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "rank_clips"},
        )
        rows = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "rank_clips":
                rows = block.input.get("scores")
                break
        if not rows:
            return {}
        out: dict[str, float] = {}
        for r in rows:
            idx = r.get("index")
            if isinstance(idx, int) and 0 <= idx < len(head):
                out[head[idx].id] = float((r.get("hook") or 0)
                                          + (r.get("clarity") or 0)
                                          + (r.get("shareable") or 0))
        if out:
            best_id = max(out, key=out.get)
            best = next(c for c in head if c.id == best_id)
            print(f"  [judge] scored {len(out)} clips; top pick {out[best_id]:.0f}/15: {best.title!r}")
        return out
    except Exception as e:
        print(f"  [judge] skipped ({type(e).__name__}: {e})")
        return {}
