"""Command-line tools for local development.

  python -m app.cli create-user --email s1234567@student.rmit.edu.au --name "Test Student"
  python -m app.cli ingest --user-id 1234567 --course-id COSC2673 --dir ../../
  python -m app.cli ask --user-id 1234567 "What should I revise before CNNs?"
  python -m app.cli graph --user-id 1234567 --course-id COSC2673 [--rebuild] [--edges]
  python -m app.cli canvas-content --user-id 1234567 --course-id 171223 [--ingest] [--no-graph]
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from app.core.security import configure_logging, hash_password
from app.database.academic_repository import get_academic_repo


def cmd_create_user(a):
    repo = get_academic_repo()
    from app.api.auth import _derive_user_id

    if repo.get_user_by_email(a.email.lower()):
        print("User exists:", repo.get_user_by_email(a.email.lower())["user_id"])
        return
    pw = a.password or getpass.getpass("Password: ")
    uid = _derive_user_id(a.email)
    repo.create_user({"user_id": uid, "full_name": a.name, "email": a.email.lower(), "api_token": None,
                      "password": hash_password(pw)})
    print("Created user", uid)


def cmd_ingest(a):
    from app.services.ingestion_service import IngestionService
    from app.services.providers import LocalFolderProvider

    resources = LocalFolderProvider(Path(a.dir)).discover(a.user_id, a.course_id)
    print(f"Discovered {len(resources)} resources")
    for r in resources:
        print(f"  - [{r.resource_type.value}] week={r.week} {r.title}")
    report = IngestionService(progress=lambda m: print("  ..", m)).ingest(
        resources, force=a.force, build_graph=not a.no_graph, use_llm=not a.no_llm
    )
    print(json.dumps(report.as_dict(), indent=2, default=str))


def cmd_ask(a):
    from app.core.auth import authorised_courses
    from app.services.answer_service import AnswerService

    courses = authorised_courses(a.user_id, a.course_id)
    resp = AnswerService().answer(a.user_id, courses, a.question, course_id=a.course_id)
    print(f"route={resp.route} intent={resp.intent} confidence={resp.confidence}\n")
    print(resp.reply)
    print("\nSources:")
    for s in resp.sources:
        loc = f"p.{s.page}" if s.page else (s.timestamp or "")
        print(f"  [{s.id}] {s.type:6} W{s.week} {s.title} {loc} ({s.support}){' — ' + s.relation if s.relation else ''}")


def cmd_purge_course(a):
    from app.database.graph_repository import GraphRepository
    from app.database.resource_repository import ResourceRepository

    GraphRepository().clear_course(a.user_id, a.course_id)
    n = ResourceRepository().delete_course(a.user_id, a.course_id)
    print(f"Removed {n} resources and the knowledge graph for course {a.course_id} (user {a.user_id})")


def cmd_canvas_content(a):
    from app.database.resource_repository import ResourceRepository
    from app.services.canvas_content import lab_notebook_resources, sync_course_content
    from app.services.ingestion_service import IngestionService
    from app.services.providers import LocalFolderProvider

    summary = sync_course_content(a.user_id, a.course_id, progress=lambda m: print("  ..", m))
    print(json.dumps(summary, indent=2))
    if not a.ingest:
        return
    folder = Path(summary["folder"]) / "lectures"
    resources = LocalFolderProvider(folder).discover(a.user_id, a.course_id)
    resources += lab_notebook_resources(a.user_id, a.course_id, Path(summary["folder"]))
    report = IngestionService(progress=lambda m: print("  ..", m)).ingest(
        resources, build_graph=not a.no_graph, use_llm=not a.no_llm
    )
    repo = ResourceRepository()
    canvas_hashes = {r.content_hash for r in repo.list(a.user_id, a.course_id)
                     if r.local_path and Path(r.local_path).is_relative_to(folder) and r.content_hash}
    dupes = [r for r in repo.list(a.user_id, a.course_id)
             if r.content_hash in canvas_hashes and not Path(r.local_path or "/").is_relative_to(folder)]
    for r in dupes:  # same bytes already ingested from Canvas: keep one copy of the evidence
        repo.delete_resource(a.user_id, r.resource_id)
    print(json.dumps({**report.as_dict(), "removed_duplicate_uploads": [r.title for r in dupes]}, indent=2, default=str))


def cmd_ingest_labs(a):
    from app.services.canvas_content import content_root, lab_notebook_resources
    from app.services.ingestion_service import IngestionService

    folder = content_root(str(a.user_id), str(a.course_id))
    resources = lab_notebook_resources(a.user_id, a.course_id, folder)
    if not resources:
        print(f"No downloaded lab notebooks in {folder}. Run canvas-content first.")
        return
    report = IngestionService(progress=lambda m: print("  ..", m)).ingest(resources, build_graph=False)
    print(json.dumps(report.as_dict(), indent=2, default=str))


def cmd_graph(a):
    from app.database.graph_repository import GraphRepository
    from app.models.graph_models import SEMANTIC_RELATIONS

    g = GraphRepository()
    if a.rebuild:
        from app.services.embedding_service import get_embedder
        from app.services.graph_extraction_service import build_course_graph

        build_course_graph(a.user_id, a.course_id, graph_repo=g, use_llm=not a.no_llm, embed=get_embedder().embed)
    print(json.dumps(g.stats(a.user_id, a.course_id), indent=2))
    if a.edges:
        edges = g.edges(a.user_id, [a.course_id], relations=[r.value for r in SEMANTIC_RELATIONS] + ["BUILDS_ON"])
        nodes = g.get_nodes(a.user_id, [e.source_node_id for e in edges] + [e.target_node_id for e in edges])
        for e in sorted(edges, key=lambda e: -e.confidence):
            print(f"  {nodes[e.source_node_id].label} -{e.relation}-> {nodes[e.target_node_id].label} "
                  f"({e.confidence:.2f}, {e.extraction_method})")


def main(argv=None):
    configure_logging()
    p = argparse.ArgumentParser(prog="rmit1ne")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("create-user"); s.add_argument("--email", required=True); s.add_argument("--name", required=True)
    s.add_argument("--password"); s.set_defaults(fn=cmd_create_user)
    s = sub.add_parser("ingest"); s.add_argument("--user-id", required=True); s.add_argument("--course-id", required=True)
    s.add_argument("--dir", required=True); s.add_argument("--force", action="store_true")
    s.add_argument("--no-graph", action="store_true"); s.add_argument("--no-llm", action="store_true"); s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("ask"); s.add_argument("--user-id", required=True); s.add_argument("--course-id")
    s.add_argument("question"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("purge-course"); s.add_argument("--user-id", required=True); s.add_argument("--course-id", required=True)
    s.set_defaults(fn=cmd_purge_course)
    s = sub.add_parser("canvas-content"); s.add_argument("--user-id", required=True); s.add_argument("--course-id", required=True)
    s.add_argument("--ingest", action="store_true"); s.add_argument("--no-graph", action="store_true")
    s.add_argument("--no-llm", action="store_true"); s.set_defaults(fn=cmd_canvas_content)
    s = sub.add_parser("ingest-labs"); s.add_argument("--user-id", required=True); s.add_argument("--course-id", required=True)
    s.set_defaults(fn=cmd_ingest_labs)
    s = sub.add_parser("graph"); s.add_argument("--user-id", required=True); s.add_argument("--course-id", required=True)
    s.add_argument("--edges", action="store_true"); s.add_argument("--rebuild", action="store_true")
    s.add_argument("--no-llm", action="store_true"); s.set_defaults(fn=cmd_graph)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
