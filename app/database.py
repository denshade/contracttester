from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_verifier_trigger(engine: Engine) -> None:
    """Add verification_trigger on databases created before that field existed."""
    if engine.dialect.name != "sqlite":
        return
    tables = inspect(engine).get_table_names()
    if "verifiers" not in tables:
        return
    columns = {column["name"] for column in inspect(engine).get_columns("verifiers")}
    if "verification_trigger" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE verifiers ADD COLUMN verification_trigger VARCHAR(500) NOT NULL DEFAULT ''")
            )


def ensure_verifier_call(engine: Engine) -> None:
    """Add the token and headers sent when a verification URL is called."""
    if engine.dialect.name != "sqlite":
        return
    tables = inspect(engine).get_table_names()
    if "verifiers" not in tables:
        return
    columns = {column["name"] for column in inspect(engine).get_columns("verifiers")}
    statements = []
    if "verification_token" not in columns:
        statements.append("ALTER TABLE verifiers ADD COLUMN verification_token VARCHAR(500) NOT NULL DEFAULT ''")
    if "verification_headers" not in columns:
        statements.append("ALTER TABLE verifiers ADD COLUMN verification_headers TEXT NOT NULL DEFAULT '[]'")
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    _upgrade_seed_triggers(engine)


def ensure_publisher_name(engine: Engine) -> None:
    """Add publisher name on databases created before that field existed."""
    if engine.dialect.name != "sqlite":
        return
    tables = inspect(engine).get_table_names()
    if "publishers" not in tables:
        return
    columns = {column["name"] for column in inspect(engine).get_columns("publishers")}
    if "name" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE publishers ADD COLUMN name VARCHAR(200) NOT NULL DEFAULT ''"))
    _fill_blank_publisher_names(engine)


def _fill_blank_publisher_names(engine: Engine) -> None:
    """Sample contracts created before publishers had names get their sample publisher."""
    from app.seed import ACTIVE_CONTRACT, BILL_PUBLISHER, DOCK_PUBLISHER, INACTIVE_CONTRACT

    pairs = (
        (ACTIVE_CONTRACT, BILL_PUBLISHER),
        (INACTIVE_CONTRACT, DOCK_PUBLISHER),
    )
    with engine.begin() as connection:
        for contract_name, publisher_name in pairs:
            connection.execute(
                text(
                    "UPDATE publishers SET name = :publisher_name "
                    "WHERE name = '' AND contract_id IN (SELECT id FROM contracts WHERE name = :contract_name)"
                ),
                {"publisher_name": publisher_name, "contract_name": contract_name},
            )


def _upgrade_seed_triggers(engine: Engine) -> None:
    """Sample verifiers created before triggers were URLs get a URL, token, and headers."""
    from app.seed import (
        ACTIVE_VERIFIER,
        DOCK_HEADER_JSON,
        DOCK_TOKEN,
        DOCK_TRIGGER,
        DOCK_VERIFIER,
        LEGACY_HEADER_JSON,
        LEGACY_TOKEN,
        LEGACY_TRIGGER,
        LEGACY_VERIFIER,
        SCHEMA_HEADER_JSON,
        SCHEMA_TOKEN,
        SCHEMA_TRIGGER,
    )

    rows = (
        (ACTIVE_VERIFIER, "gitlab:schema-shape", SCHEMA_TRIGGER, SCHEMA_TOKEN, SCHEMA_HEADER_JSON),
        (LEGACY_VERIFIER, "gitlab:legacy-checksum", LEGACY_TRIGGER, LEGACY_TOKEN, LEGACY_HEADER_JSON),
        (DOCK_VERIFIER, "gitlab:dock-window", DOCK_TRIGGER, DOCK_TOKEN, DOCK_HEADER_JSON),
    )
    with engine.begin() as connection:
        for name, old, trigger, token, headers in rows:
            connection.execute(
                text(
                    "UPDATE verifiers SET verification_trigger = :trigger, "
                    "verification_token = :token, verification_headers = :headers "
                    "WHERE name = :name AND verification_trigger IN ('', :old)"
                ),
                {"name": name, "old": old, "trigger": trigger, "token": token, "headers": headers},
            )


def ensure_statement_fields(engine: Engine) -> None:
    """Rename expected state to state, and add verb, expected outcome, and headers."""
    if engine.dialect.name != "sqlite":
        return
    tables = inspect(engine).get_table_names()
    if "statements" not in tables:
        return
    columns = {column["name"] for column in inspect(engine).get_columns("statements")}
    with engine.begin() as connection:
        if "expected_state" in columns and "state" not in columns:
            connection.execute(text("ALTER TABLE statements RENAME COLUMN expected_state TO state"))
        if "verb" not in columns:
            connection.execute(text("ALTER TABLE statements ADD COLUMN verb VARCHAR(16) NOT NULL DEFAULT ''"))
        if "expected_outcome" not in columns:
            connection.execute(text("ALTER TABLE statements ADD COLUMN expected_outcome VARCHAR(2000) NOT NULL DEFAULT ''"))
        if "expected_headers" not in columns:
            connection.execute(text("ALTER TABLE statements ADD COLUMN expected_headers TEXT NOT NULL DEFAULT '[]'"))
    _split_legacy_statement_calls(engine)
    _upgrade_seed_statement_outcomes(engine)


def _split_legacy_statement_calls(engine: Engine) -> None:
    """Older statements stored the verb in the endpoint, and had no expected outcome."""
    from app.http_methods import HTTP_VERBS

    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, trigger, verb, state, expected_outcome FROM statements")
        ).mappings()
        for row in rows:
            verb = (row["verb"] or "").strip()
            trigger = row["trigger"] or ""
            outcome = (row["expected_outcome"] or "").strip()
            new_verb = verb
            new_trigger = trigger
            if not verb:
                head, separator, rest = trigger.partition(" ")
                if separator and head.upper() in HTTP_VERBS and rest.strip():
                    new_verb = head.upper()
                    new_trigger = rest.strip()
                else:
                    new_verb = "GET"
            new_outcome = outcome or (row["state"] or "").strip() or "Recorded"
            if new_verb == verb and new_trigger == trigger and new_outcome == (row["expected_outcome"] or ""):
                continue
            connection.execute(
                text(
                    "UPDATE statements SET verb = :verb, trigger = :trigger, expected_outcome = :outcome "
                    "WHERE id = :id"
                ),
                {"verb": new_verb, "trigger": new_trigger, "outcome": new_outcome, "id": row["id"]},
            )


def _upgrade_seed_statement_outcomes(engine: Engine) -> None:
    """Sample statements migrated from a status-only outcome get their sample outcome and headers."""
    from app.seed import (
        BILL_GET,
        BILL_GET_HEADER_LINES,
        BILL_GET_OUTCOME,
        BILL_GET_STATE,
        BILL_GET_VERB,
        BILL_POST,
        BILL_POST_HEADER_LINES,
        BILL_POST_OUTCOME,
        BILL_POST_STATE,
        BILL_POST_VERB,
        DOCK_HEADER_LINES,
        DOCK_OUTCOME,
        DOCK_POST,
        DOCK_STATE,
        DOCK_VERB,
    )
    from app.triggers import dump_headers, parse_header_block

    rows = (
        (BILL_GET_VERB, BILL_GET, BILL_GET_STATE, BILL_GET_OUTCOME, BILL_GET_HEADER_LINES),
        (BILL_POST_VERB, BILL_POST, BILL_POST_STATE, BILL_POST_OUTCOME, BILL_POST_HEADER_LINES),
        (DOCK_VERB, DOCK_POST, DOCK_STATE, DOCK_OUTCOME, DOCK_HEADER_LINES),
    )
    with engine.begin() as connection:
        for verb, trigger, state, outcome, header_lines in rows:
            connection.execute(
                text(
                    "UPDATE statements SET expected_outcome = :outcome, expected_headers = :headers "
                    "WHERE verb = :verb AND trigger = :trigger AND state = :state "
                    "AND expected_outcome = :state AND expected_headers = '[]'"
                ),
                {
                    "verb": verb,
                    "trigger": trigger,
                    "state": state,
                    "outcome": outcome,
                    "headers": dump_headers(parse_header_block(header_lines)),
                },
            )
