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
    _fill_blank_seed_triggers(engine)


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


def _fill_blank_seed_triggers(engine: Engine) -> None:
    """Databases created before the trigger field have an empty value on the sample verifiers."""
    from app.seed import (
        ACTIVE_VERIFIER,
        DOCK_TRIGGER,
        DOCK_VERIFIER,
        LEGACY_TRIGGER,
        LEGACY_VERIFIER,
        SCHEMA_TRIGGER,
    )

    pairs = (
        (ACTIVE_VERIFIER, SCHEMA_TRIGGER),
        (LEGACY_VERIFIER, LEGACY_TRIGGER),
        (DOCK_VERIFIER, DOCK_TRIGGER),
    )
    with engine.begin() as connection:
        for name, trigger in pairs:
            connection.execute(
                text(
                    "UPDATE verifiers SET verification_trigger = :trigger "
                    "WHERE name = :name AND verification_trigger = ''"
                ),
                {"name": name, "trigger": trigger},
            )
