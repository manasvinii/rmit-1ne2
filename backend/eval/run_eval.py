"""Compare retrieval strategies on a labelled question set.

  python -m eval.run_eval --user-id 3999001 --dataset eval/datasets/cosc2673_seed.jsonl [--modes vector graph hybrid]
                          [--k 5] [--judge] [--include-draft]

Modes (same answer pipeline, different retrieval):
  vector  every question forced through VECTOR_RAG (dense + keyword RRF)
  graph   graph intents answered from graph facts and their provenance only (no extra vector evidence)
  hybrid  the production router (STRUCTURED_CANVAS / VECTOR_RAG / GRAPH / GRAPH_VECTOR)

Metrics per item, averaged per mode and category:
  evidence_recall@k     share of gold evidence locations matched by the top-k sources
  evidence_precision@k  share of the top-k sources that match some gold location
  citation_correctness  share of [S#] markers in the reply that point to an existing source which matches gold
                        (or, when no gold evidence is given, simply exists)
  concept_recall        share of expected concepts named in the reply
  route_accuracy        hybrid only: router output equals expected_route
  latency_ms            wall-clock time of answer()
  judge_score           optional 1-5 groundedness score from an LLM judge (needs OPENAI_API_KEY)

Only items with label_status == "reviewed" are scored unless --include-draft is passed; results are
written to eval/results/ and nothing is reported that was not measured.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.core.auth import authorised_courses
from app.core.security import configure_logging
from app.services.answer_service import AnswerService
from app.services.entity_resolution import normalize
from app.services.llm_service import get_llm
from app.services.query_router import Intent, Route, route_query
from eval.schema import EvalItem

RESULTS_DIR = Path(__file__).resolve().parent / "results"
_GRAPH_INTENTS = {Intent.PREREQUISITES, Intent.CONCEPT_TIMELINE, Intent.CONCEPT_PROGRESSION,
                  Intent.LECTURE_CONNECTION, Intent.CONCEPT_RELATION, Intent.ASSIGNMENT_REVISION}


def load_dataset(path: Path, include_draft: bool) -> list[EvalItem]:
    items = [EvalItem.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]
    return items if include_draft else [i for i in items if i.label_status == "reviewed"]


def routed_for(mode: str, question: str):
    base = route_query(question)
    if mode == "hybrid":
        return base
    if mode == "vector":
        if base.route == Route.STRUCTURED_CANVAS:
            return base
        intent = base.intent if base.intent == Intent.LOCATE else Intent.LECTURE_FACT
        return replace(base, route=Route.VECTOR_RAG, intent=intent)
    if mode == "graph":
        if base.intent in _GRAPH_INTENTS:
            return replace(base, route=Route.GRAPH)
        return base
    raise ValueError(mode)


def concept_mentioned(concept: str, text: str) -> bool:
    return normalize(concept) in normalize(text)


def judge(item: EvalItem, reply: str, sources: list[dict]):
    llm = get_llm()
    if llm is None:
        return None
    evidence = "\n".join(f"[{s['id']}] {s.get('snippet') or ''}" for s in sources)
    out = llm.complete_json(
        "You grade whether an answer is supported by the given evidence excerpts. Ignore style.",
        f"Question: {item.question}\n\nEvidence:\n{evidence}\n\nAnswer:\n{reply}",
        {"type": "object", "additionalProperties": False, "required": ["score", "reason"],
         "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5}, "reason": {"type": "string"}}},
        "groundedness",
    )
    return out.get("score") if out else None


def score_item(item: EvalItem, mode: str, user_id: str, k: int, use_judge: bool) -> dict:
    courses = authorised_courses(user_id, item.course_id)
    routed = routed_for(mode, item.question)
    t0 = time.perf_counter()
    resp = AnswerService().answer(user_id, courses, item.question, course_id=item.course_id, routed=routed)
    latency = (time.perf_counter() - t0) * 1000
    sources = [s.model_dump() for s in resp.sources]
    top = sources[:k]
    gold = item.expected_evidence

    row = {"id": item.id, "category": item.category, "mode": mode, "route": resp.route,
           "latency_ms": round(latency, 1), "n_sources": len(sources)}
    if gold:
        row["evidence_recall@k"] = sum(any(g.matches(s) for s in top) for g in gold) / len(gold)
        row["evidence_precision@k"] = (sum(any(g.matches(s) for g in gold) for s in top) / len(top)) if top else 0.0
    cited = re.findall(r"\[(S\d+)\]", resp.reply)
    if cited:
        by_id = {s["id"]: s for s in sources}
        ok = [c for c in cited if c in by_id and (not gold or any(g.matches(by_id[c]) for g in gold))]
        row["citation_correctness"] = len(ok) / len(cited)
    if item.expected_concepts:
        row["concept_recall"] = sum(concept_mentioned(c, resp.reply) for c in item.expected_concepts) / len(item.expected_concepts)
    if mode == "hybrid" and item.expected_route:
        row["route_accuracy"] = float(resp.route == item.expected_route)
    if use_judge:
        row["judge_score"] = judge(item, resp.reply, top)
    return row


METRICS = ["evidence_recall@k", "evidence_precision@k", "citation_correctness", "concept_recall",
           "route_accuracy", "latency_ms", "judge_score"]


def summarise(rows: list[dict]) -> dict:
    out: dict = defaultdict(dict)
    for key_fn, label in ((lambda r: r["mode"], "by_mode"), (lambda r: (r["mode"], r["category"]), "by_mode_category")):
        groups: dict = defaultdict(list)
        for r in rows:
            groups[key_fn(r)].append(r)
        for key, rs in groups.items():
            stats = {"n": len(rs)}
            for m in METRICS:
                vals = [r[m] for r in rs if r.get(m) is not None]
                if vals:
                    stats[m] = round(statistics.mean(vals), 3)
                    stats[f"{m}_n"] = len(vals)
            out[label]["/".join(key) if isinstance(key, tuple) else key] = stats
    return out


def to_markdown(summary: dict, k: int) -> str:
    cols = ["n", "evidence_recall@k", "evidence_precision@k", "citation_correctness", "concept_recall",
            "route_accuracy", "latency_ms", "judge_score"]
    lines = [f"| mode | {' | '.join(c.replace('@k', f'@{k}') for c in cols)} |", "|" + "---|" * (len(cols) + 1)]
    for mode, s in summary["by_mode"].items():
        lines.append(f"| {mode} | " + " | ".join(str(s.get(c, "–")) for c in cols) + " |")
    return "\n".join(lines)


def main(argv=None):
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", required=True)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--modes", nargs="+", default=["vector", "graph", "hybrid"])
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--judge", action="store_true")
    p.add_argument("--include-draft", action="store_true", help="also score items whose labels are not reviewed")
    a = p.parse_args(argv)

    items = load_dataset(a.dataset, a.include_draft)
    if not items:
        raise SystemExit("No reviewed items in the dataset (use --include-draft to score draft labels).")
    rows = [score_item(i, m, a.user_id, a.k, a.judge) for m in a.modes for i in items]
    summary = summarise(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"eval-{stamp}.json"
    out.write_text(json.dumps({
        "dataset": str(a.dataset), "k": a.k, "include_draft": a.include_draft, "items": len(items),
        "summary": summary, "rows": rows,
    }, indent=2))
    print(to_markdown(summary, a.k))
    print(f"\nlabels: {'draft + reviewed' if a.include_draft else 'reviewed only'}; details in {out}")


if __name__ == "__main__":
    main()
