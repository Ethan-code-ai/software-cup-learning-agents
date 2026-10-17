from sqlalchemy import inspect, text

from app.db.session import get_engine


DOCUMENT_COLUMN_DEFINITIONS = {
    "visibility": "VARCHAR(40) NOT NULL DEFAULT 'course'",
    "owner_user_id": "INTEGER",
    "file_name": "VARCHAR(240)",
    "mime_type": "VARCHAR(160)",
    "file_size": "INTEGER",
    "parser_name": "VARCHAR(80)",
}

AGENT_RUN_STEP_COLUMN_DEFINITIONS = {
    "execution_metadata": "JSON NOT NULL DEFAULT '{}'",
}

LEARNING_PATH_COLUMN_DEFINITIONS = {
    "learning_intent": "JSON NOT NULL DEFAULT '{}'",
    "target_concept_ids": "JSON NOT NULL DEFAULT '[]'",
    "intent_confidence": "FLOAT NOT NULL DEFAULT 0",
    "milestones": "JSON NOT NULL DEFAULT '[]'",
}

LEARNING_PATH_ITEM_COLUMN_DEFINITIONS = {
    "node_role": "VARCHAR(40) NOT NULL DEFAULT 'target'",
    "activity_type": "VARCHAR(80) NOT NULL DEFAULT 'explanation'",
    "estimated_minutes": "INTEGER NOT NULL DEFAULT 20",
    "success_criterion": "TEXT NOT NULL DEFAULT '能够完成本节点学习目标。'",
}

GENERATED_RESOURCE_COLUMN_DEFINITIONS = {
    "animation_spec": "JSON",
}


def ensure_document_columns(database_url: str | None = None) -> None:
    _ensure_columns("documents", DOCUMENT_COLUMN_DEFINITIONS, database_url)


def ensure_agent_run_step_columns(database_url: str | None = None) -> None:
    _ensure_columns("agent_run_steps", AGENT_RUN_STEP_COLUMN_DEFINITIONS, database_url)


def ensure_learning_path_columns(database_url: str | None = None) -> None:
    _ensure_columns("learning_paths", LEARNING_PATH_COLUMN_DEFINITIONS, database_url)
    _ensure_columns("learning_path_items", LEARNING_PATH_ITEM_COLUMN_DEFINITIONS, database_url)


def ensure_generated_resource_columns(database_url: str | None = None) -> None:
    _ensure_columns("generated_resources", GENERATED_RESOURCE_COLUMN_DEFINITIONS, database_url)


def _ensure_columns(table_name: str, definitions: dict[str, str], database_url: str | None = None) -> None:
    engine = get_engine(database_url)
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    missing = [
        (name, definition)
        for name, definition in definitions.items()
        if name not in existing
    ]
    if not missing:
        return
    with engine.begin() as connection:
        for name, definition in missing:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))
