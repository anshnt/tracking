"""Test fixtures. Needs TEST_DATABASE_URL (a Postgres URL; the database is created if missing).

Fixtures: db, make_employee, client_for, override_settings (see docstrings below).
"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    raise pytest.UsageError(
        "set TEST_DATABASE_URL, e.g. postgresql+psycopg://user:pw@127.0.0.1:5433/name"
    )

# Must be set before portal is imported (settings and engine are cached).
os.environ["DATABASE_URL"] = TEST_DB
os.environ["PORTAL_ENV"] = "development"
os.environ["PUBLIC_ORIGIN"] = "http://testserver"
os.environ.pop("PORTAL_DEV_AUTH", None)

from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from alembic import command
from portal import auth
from portal.config import Settings, get_settings
from portal.db import get_engine, session_factory
from portal.main import create_app
from portal.models import Employee

API_DIR = Path(__file__).resolve().parents[1]
CSRF_HEADERS = {"Origin": "http://testserver", "X-Requested-With": "portal"}


def _ensure_database() -> None:
    url = make_url(TEST_DB)
    admin = psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname="postgres",
        autocommit=True,
    )
    with admin:
        if not admin.execute(
            "select 1 from pg_database where datname = %s", (url.database,)
        ).fetchone():
            admin.execute(sql.SQL("create database {}").format(sql.Identifier(url.database)))


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    _ensure_database()
    command.upgrade(Config(str(API_DIR / "alembic.ini")), "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def _clean():
    get_settings.cache_clear()
    auth.reset_oidc_cache()
    yield
    with get_engine().begin() as conn:
        tables = (
            conn.execute(
                text(
                    "select tablename from pg_tables where schemaname='public' "
                    "and tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        conn.execute(text("truncate " + ", ".join(tables) + " restart identity cascade"))


@pytest.fixture
def db():
    """A SQLAlchemy Session. Commit yourself; data is truncated after each test."""
    with session_factory()() as session:
        yield session


@pytest.fixture
def make_employee(db):
    """make_employee(roles=None, manager=None, **fields) -> committed Employee (default roles: employee)."""

    def make(roles=None, manager=None, **fields) -> Employee:
        n = uuid.uuid4().hex[:8]
        emp = Employee(
            oidc_subject=fields.pop("oidc_subject", f"sub-{n}"),
            display_name=fields.pop("display_name", f"Person {n}"),
            email=fields.pop("email", f"{n}@example.invalid"),
            roles=roles or ["employee"],
            manager_id=manager.id if manager else None,
            **fields,
        )
        db.add(emp)
        db.commit()
        return emp

    return make


@pytest.fixture
def app():
    """Fresh app per test (so dependency_overrides never leak)."""
    return create_app()


@pytest.fixture
def client_for(app, db):
    """client_for(employee) -> TestClient logged in as employee, with the CSRF headers
    (Origin: http://testserver, X-Requested-With: portal) already set on every request."""

    def make(employee: Employee, **kwargs) -> TestClient:
        token = auth.create_session(db, employee, get_settings())
        db.commit()
        client = TestClient(app, headers=CSRF_HEADERS, **kwargs)
        client.cookies.set(get_settings().session_cookie_name, token)
        return client

    return make


@pytest.fixture
def override_settings(app):
    """override_settings(**fields): make the app use Settings(**fields) (on top of the test env)."""

    def apply(**fields) -> Settings:
        settings = Settings(**fields)
        app.dependency_overrides[get_settings] = lambda: settings
        return settings

    return apply
