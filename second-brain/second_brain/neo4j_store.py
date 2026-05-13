from __future__ import annotations

import os
from typing import Any

from neo4j import GraphDatabase, Driver

from second_brain import refs

_DRIVER: Driver | None = None


def neo4j_driver() -> Driver:
    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER
    uri = (os.environ.get("NEO4J_URI") or "bolt://127.0.0.1:7687").strip()
    user = (os.environ.get("NEO4J_USER") or "neo4j").strip()
    password = (os.environ.get("NEO4J_PASSWORD") or "").strip()
    if not password:
        raise RuntimeError("NEO4J_PASSWORD is required")
    _DRIVER = GraphDatabase.driver(uri, auth=(user, password))
    return _DRIVER


def close_driver() -> None:
    global _DRIVER
    if _DRIVER is not None:
        _DRIVER.close()
        _DRIVER = None


def ensure_constraints(driver: Driver) -> None:
    stmts = [
        "CREATE CONSTRAINT sb_story_ref IF NOT EXISTS FOR (n:Story) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_task_ref IF NOT EXISTS FOR (n:Task) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_document_ref IF NOT EXISTS FOR (n:Document) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_member_ref IF NOT EXISTS FOR (n:Member) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_comment_ref IF NOT EXISTS FOR (n:Comment) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_wikicomment_ref IF NOT EXISTS FOR (n:WikiComment) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_decision_ref IF NOT EXISTS FOR (n:Decision) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_lesson_ref IF NOT EXISTS FOR (n:LessonLearned) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_feedback_ref IF NOT EXISTS FOR (n:Feedback) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_commit_ref IF NOT EXISTS FOR (n:Commit) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_project_ref IF NOT EXISTS FOR (n:Project) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codefile_ref IF NOT EXISTS FOR (n:CodeFile) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codefunction_ref IF NOT EXISTS FOR (n:CodeFunction) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codecontroller_ref IF NOT EXISTS FOR (n:CodeController) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codeendpoint_ref IF NOT EXISTS FOR (n:CodeEndpoint) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codedto_ref IF NOT EXISTS FOR (n:CodeDTO) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codefield_ref IF NOT EXISTS FOR (n:CodeField) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codedecorator_ref IF NOT EXISTS FOR (n:CodeDecorator) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_codebusinessrule_ref IF NOT EXISTS FOR (n:BusinessRule) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_databasetable_ref IF NOT EXISTS FOR (n:DatabaseTable) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_kafkatopic_ref IF NOT EXISTS FOR (n:KafkaTopic) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_externalapi_ref IF NOT EXISTS FOR (n:ExternalAPI) REQUIRE n.ref IS UNIQUE",
        "CREATE CONSTRAINT sb_release_ref IF NOT EXISTS FOR (n:Release) REQUIRE n.ref IS UNIQUE",
    ]
    with driver.session() as session:
        for cypher in stmts:
            session.run(cypher)


def run_read(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    driver = neo4j_driver()
    params = params or {}
    with driver.session() as session:
        result = session.run(cypher, params)
        return [record.data() for record in result]


def run_write(cypher: str, params: dict[str, Any] | None = None) -> None:
    driver = neo4j_driver()
    params = params or {}

    def _tx(tx):  # noqa: ANN001
        tx.run(cypher, params)

    with driver.session() as session:
        session.execute_write(_tx)


def node_ref(project_id: int, kind: str, agile_id: int) -> str:
    return refs.node_ref(project_id, kind, agile_id)


def node_ref_slug(project_id: int, kind: str, external_id: str) -> str:
    return refs.node_ref_slug(project_id, kind, external_id)


def global_ref(kind: str, key: str | None = None) -> str:
    return refs.global_ref(kind, key)
