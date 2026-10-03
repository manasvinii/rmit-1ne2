"""Knowledge-graph storage on relational tables (kg_nodes / kg_edges / kg_edge_evidence).

Multi-hop traversal uses WITH RECURSIVE (portable across SQLite and Postgres). Every method is
scoped by user_id (+ course_ids) so traversal can never cross into another student's graph.
Swap this class for a Neo4j-backed implementation with the same methods if needed.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from app.database.db import Database, get_db
from app.models.graph_models import EdgeEvidence, GraphEdge, GraphNode
from app.services.resource_ids import make_edge_id, make_id, make_node_id


def _in(vals: Sequence) -> str:
    return ", ".join("?" * len(vals))


class GraphRepository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    # ------------------------------------------------------------------ writes
    def clear_course(self, user_id: str, course_id: str) -> None:
        # evidence/aliases cascade from nodes/edges
        self.db.execute("DELETE FROM kg_edges WHERE user_id = ? AND course_id = ?", (user_id, course_id))
        self.db.execute("DELETE FROM kg_nodes WHERE user_id = ? AND course_id = ?", (user_id, course_id))

    def upsert_node(
        self,
        user_id: str,
        course_id: str,
        node_type: str,
        node_key: str,
        label: str,
        description: Optional[str] = None,
        properties: Optional[dict] = None,
    ) -> str:
        node_id = make_node_id(user_id, course_id, node_type, node_key)
        self.db.execute(
            "INSERT INTO kg_nodes (node_id, user_id, course_id, node_type, node_key, label, description, "
            "properties) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (node_id) DO UPDATE SET "
            "label = excluded.label, description = COALESCE(excluded.description, kg_nodes.description), "
            "properties = excluded.properties",
            (node_id, user_id, course_id, node_type, node_key, label, description,
             self.db.json(properties or {})),
        )
        return node_id

    def add_aliases(self, user_id: str, course_id: str, node_id: str, aliases: Iterable[tuple[str, str]]) -> None:
        sql = (
            "INSERT INTO kg_node_aliases (node_id, user_id, course_id, alias, alias_norm) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (node_id, alias_norm) DO NOTHING"
        )
        self.db.executemany(sql, [(node_id, user_id, course_id, a, n) for a, n in aliases if n])

    def upsert_edge(
        self,
        user_id: str,
        course_id: str,
        source_id: str,
        relation: str,
        target_id: str,
        confidence: float,
        method: str,
        properties: Optional[dict] = None,
        evidence: Sequence[EdgeEvidence] = (),
    ) -> str:
        edge_id = make_edge_id(user_id, course_id, source_id, relation, target_id)
        self.db.execute(
            "INSERT INTO kg_edges (edge_id, user_id, course_id, source_node_id, relation, target_node_id, "
            "confidence, extraction_method, properties) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (edge_id) DO UPDATE SET confidence = excluded.confidence, "
            "extraction_method = excluded.extraction_method, properties = excluded.properties",
            (edge_id, user_id, course_id, source_id, relation, target_id, round(confidence, 4), method,
             self.db.json(properties or {})),
        )
        if evidence:
            self.db.executemany(
                "INSERT INTO kg_edge_evidence (evidence_id, edge_id, user_id, chunk_id, resource_id, page_number, "
                "start_time, end_time, quote, extraction_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (evidence_id) DO NOTHING",
                [
                    (make_id("ev", edge_id, ev.chunk_id, ev.quote, ev.extraction_method), edge_id, user_id,
                     ev.chunk_id, ev.resource_id, ev.page_number, ev.start_time, ev.end_time, ev.quote,
                     ev.extraction_method)
                    for ev in evidence
                ],
            )
        return edge_id

    # ------------------------------------------------------------------ reads
    def _node(self, r: dict) -> GraphNode:
        return GraphNode(
            node_id=r["node_id"], node_type=r["node_type"], node_key=r["node_key"], label=r["label"],
            course_id=r["course_id"], description=r["description"], properties=self.db.load_json(r["properties"]),
        )

    def _edge(self, r: dict) -> GraphEdge:
        return GraphEdge(
            edge_id=r["edge_id"], source_node_id=r["source_node_id"], relation=r["relation"],
            target_node_id=r["target_node_id"], confidence=float(r["confidence"]),
            extraction_method=r["extraction_method"], course_id=r["course_id"],
            properties=self.db.load_json(r["properties"]),
        )

    def get_nodes(self, user_id: str, node_ids: Sequence[str]) -> dict[str, GraphNode]:
        ids = list(dict.fromkeys(node_ids))
        if not ids:
            return {}
        rows = self.db.fetchall(
            f"SELECT * FROM kg_nodes WHERE user_id = ? AND node_id IN ({_in(ids)})", [user_id, *ids]
        )
        return {r["node_id"]: self._node(r) for r in rows}

    def list_nodes(
        self, user_id: str, course_ids: Sequence[str], node_types: Optional[Sequence[str]] = None
    ) -> list[GraphNode]:
        if not course_ids:
            return []
        sql = f"SELECT * FROM kg_nodes WHERE user_id = ? AND course_id IN ({_in(course_ids)})"
        params: list = [user_id, *course_ids]
        if node_types:
            sql += f" AND node_type IN ({_in(node_types)})"
            params += list(node_types)
        return [self._node(r) for r in self.db.fetchall(sql, params)]

    def find_by_alias(self, user_id: str, course_ids: Sequence[str], alias_norms: Sequence[str]) -> dict[str, list[str]]:
        """alias_norm -> [node_id]"""
        alias_norms = list(dict.fromkeys(a for a in alias_norms if a))
        if not alias_norms or not course_ids:
            return {}
        rows = self.db.fetchall(
            f"SELECT alias_norm, node_id FROM kg_node_aliases WHERE user_id = ? AND course_id IN ({_in(course_ids)}) "
            f"AND alias_norm IN ({_in(alias_norms)})",
            [user_id, *course_ids, *alias_norms],
        )
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["alias_norm"], []).append(r["node_id"])
        return out

    def list_aliases(self, user_id: str, course_ids: Sequence[str]) -> list[dict]:
        if not course_ids:
            return []
        return self.db.fetchall(
            f"SELECT node_id, alias, alias_norm FROM kg_node_aliases WHERE user_id = ? AND course_id IN ({_in(course_ids)})",
            [user_id, *course_ids],
        )

    def edges(
        self,
        user_id: str,
        course_ids: Sequence[str],
        node_ids: Optional[Sequence[str]] = None,
        relations: Optional[Sequence[str]] = None,
        direction: str = "out",  # out | in | both
        min_confidence: float = 0.0,
    ) -> list[GraphEdge]:
        if not course_ids:
            return []
        sql = f"SELECT * FROM kg_edges WHERE user_id = ? AND course_id IN ({_in(course_ids)}) AND confidence >= ?"
        params: list = [user_id, *course_ids, min_confidence]
        if node_ids is not None:
            ids = list(node_ids)
            if not ids:
                return []
            if direction == "out":
                sql += f" AND source_node_id IN ({_in(ids)})"
                params += ids
            elif direction == "in":
                sql += f" AND target_node_id IN ({_in(ids)})"
                params += ids
            else:
                sql += f" AND (source_node_id IN ({_in(ids)}) OR target_node_id IN ({_in(ids)}))"
                params += ids + ids
        if relations:
            sql += f" AND relation IN ({_in(relations)})"
            params += list(relations)
        return [self._edge(r) for r in self.db.fetchall(sql, params)]

    def evidence_for(self, user_id: str, edge_ids: Sequence[str]) -> dict[str, list[EdgeEvidence]]:
        ids = list(dict.fromkeys(edge_ids))
        if not ids:
            return {}
        rows = self.db.fetchall(
            f"SELECT * FROM kg_edge_evidence WHERE user_id = ? AND edge_id IN ({_in(ids)})", [user_id, *ids]
        )
        out: dict[str, list[EdgeEvidence]] = {}
        for r in rows:
            out.setdefault(r["edge_id"], []).append(
                EdgeEvidence(
                    chunk_id=r["chunk_id"], resource_id=r["resource_id"], page_number=r["page_number"],
                    start_time=r["start_time"], end_time=r["end_time"], quote=r["quote"],
                    extraction_method=r["extraction_method"],
                )
            )
        return out

    def traverse(
        self,
        user_id: str,
        course_ids: Sequence[str],
        start_ids: Sequence[str],
        relations: Sequence[str],
        max_depth: int = 3,
        min_confidence: float = 0.5,
        reverse: bool = False,
    ) -> dict[str, int]:
        """Multi-hop walk along `relations` (source->target, or target->source if reverse).

        Returns {node_id: min_depth}, excluding the start nodes. Cycle-safe via path tracking.
        """
        if not start_ids or not relations or not course_ids:
            return {}
        nxt, cur = ("source_node_id", "target_node_id") if reverse else ("target_node_id", "source_node_id")
        sql = f"""
        WITH RECURSIVE walk(node_id, depth, path) AS (
            SELECT node_id, 0, ',' || node_id || ','
              FROM kg_nodes WHERE user_id = ? AND node_id IN ({_in(start_ids)})
            UNION ALL
            SELECT e.{nxt}, w.depth + 1, w.path || e.{nxt} || ','
              FROM walk w
              JOIN kg_edges e ON e.{cur} = w.node_id
             WHERE e.user_id = ? AND e.course_id IN ({_in(course_ids)})
               AND e.relation IN ({_in(relations)}) AND e.confidence >= ?
               AND w.depth < ? AND w.path NOT LIKE '%,' || e.{nxt} || ',%'
        )
        SELECT node_id, MIN(depth) AS depth FROM walk GROUP BY node_id
        """
        params = [user_id, *start_ids, user_id, *course_ids, *relations, min_confidence, max_depth]
        rows = self.db.fetchall(sql, params)
        starts = set(start_ids)
        return {r["node_id"]: int(r["depth"]) for r in rows if r["node_id"] not in starts}

    def stats(self, user_id: str, course_id: str) -> dict:
        nodes = self.db.fetchall(
            "SELECT node_type, COUNT(*) AS n FROM kg_nodes WHERE user_id = ? AND course_id = ? GROUP BY node_type",
            (user_id, course_id),
        )
        edges = self.db.fetchall(
            "SELECT relation, COUNT(*) AS n FROM kg_edges WHERE user_id = ? AND course_id = ? GROUP BY relation",
            (user_id, course_id),
        )
        return {
            "nodes": {r["node_type"]: r["n"] for r in nodes},
            "edges": {r["relation"]: r["n"] for r in edges},
        }
