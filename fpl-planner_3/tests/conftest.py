import os
import pytest


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Isolert SQLite-base per test. Nullstiller den globale motoren."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.sqlite'}")
    from fplplanner import db
    db._engine = None
    db.create_all()
    yield db
    db._engine = None
