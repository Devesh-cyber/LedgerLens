import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest

# Env vars must exist before src.api.routes is imported (it builds the
# Supabase client and reads DATABASE_URL at import time).
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient wired to a throwaway sqlite DB and a mocked Supabase
    Storage client, so tests never touch the real Supabase project."""
    db_path = tmp_path / f"test_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    # Reload the DB engine + app fresh against the new DATABASE_URL.
    import importlib
    import src.core.database as database_module
    importlib.reload(database_module)

    import src.api.routes as routes_module
    importlib.reload(routes_module)

    import main as main_module
    importlib.reload(main_module)

    database_module.init_db()

    mock_bucket = MagicMock()
    mock_bucket.upload.return_value = None
    mock_bucket.get_public_url.side_effect = (
        lambda path: f"https://example.supabase.co/storage/v1/object/public/invoices/{path}"
    )
    mock_client = MagicMock()
    mock_client.storage.from_.return_value = mock_bucket
    routes_module.supabase = mock_client

    from fastapi.testclient import TestClient
    with TestClient(main_module.app) as test_client:
        test_client.routes_module = routes_module
        yield test_client