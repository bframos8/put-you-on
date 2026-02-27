import pytest
from unittest.mock import MagicMock, patch, call
import psycopg

from data_pipeline.db.initializer import DatabaseInitializer


@pytest.fixture
def mock_db_manager():
    mock = MagicMock()
    mock.conn = MagicMock()
    mock.cur = MagicMock()
    return mock


@pytest.fixture
def initializer(mock_db_manager):
    return DatabaseInitializer(mock_db_manager)


class TestInit:
    def test_stores_db_manager_reference(self, mock_db_manager):
        initializer = DatabaseInitializer(mock_db_manager)
        assert initializer.database_manager is mock_db_manager

    def test_uses_conn_and_cur_from_db_manager(self, mock_db_manager):
        initializer = DatabaseInitializer(mock_db_manager)
        assert initializer.conn is mock_db_manager.conn
        assert initializer.cur is mock_db_manager.cur


class TestCreateTable:
    def test_create_table_executes_and_commits(self, initializer, mock_db_manager):
        initializer.create_table("songs", ["id SERIAL PRIMARY KEY", "title TEXT"])

        mock_db_manager.cur.execute.assert_called_once()
        mock_db_manager.conn.commit.assert_called_once()

    def test_create_table_empty_columns_raises(self, initializer):
        with pytest.raises(ValueError, match="Columns list is empty"):
            initializer.create_table("songs", [])

    def test_create_table_empty_name_raises(self, initializer):
        with pytest.raises(ValueError, match="Table name is empty"):
            initializer.create_table("", ["id SERIAL PRIMARY KEY"])

    def test_create_table_rollback_on_error(self, initializer, mock_db_manager):
        mock_db_manager.cur.execute.side_effect = psycopg.Error("db error")

        with pytest.raises(ValueError, match="An error creating table occurred"):
            initializer.create_table("songs", ["id SERIAL PRIMARY KEY"])

        mock_db_manager.conn.rollback.assert_called_once()

    def test_create_table_uses_if_not_exists(self, initializer, mock_db_manager):
        initializer.create_table("songs", ["id SERIAL PRIMARY KEY"])

        query_str = str(mock_db_manager.cur.execute.call_args[0][0])
        assert "IF NOT EXISTS" in query_str


class TestCreateType:
    def test_create_type_executes_and_commits(self, initializer, mock_db_manager):
        mock_db_manager.cur.fetchone.return_value = None  # type doesn't exist

        initializer.create_type("work_status_enum", ["pending", "in_progress", "completed"])

        mock_db_manager.conn.commit.assert_called_once()

    def test_create_type_skips_if_already_exists(self, initializer, mock_db_manager):
        mock_db_manager.cur.fetchone.return_value = (1,)  # type exists

        initializer.create_type("work_status_enum", ["pending", "completed"])

        # execute is called once for the SELECT check, but not for CREATE
        mock_db_manager.conn.commit.assert_not_called()

    def test_create_type_empty_values_raises(self, initializer):
        with pytest.raises(ValueError, match="Values list is empty"):
            initializer.create_type("my_enum", [])

    def test_create_type_empty_name_raises(self, initializer):
        with pytest.raises(ValueError, match="Type name is empty"):
            initializer.create_type("", ["val1"])

    def test_create_type_rollback_on_error(self, initializer, mock_db_manager):
        mock_db_manager.cur.fetchone.return_value = None  # type doesn't exist
        # First execute (SELECT check) succeeds, second (CREATE) fails
        mock_db_manager.cur.execute.side_effect = [None, psycopg.Error("db error")]

        with pytest.raises(ValueError, match="An error creating type occurred"):
            initializer.create_type("my_enum", ["val1", "val2"])

        mock_db_manager.conn.rollback.assert_called_once()

    def test_create_type_checks_existence_first(self, initializer, mock_db_manager):
        mock_db_manager.cur.fetchone.return_value = None

        initializer.create_type("work_status_enum", ["pending"])

        # First call should be the SELECT pg_type check
        first_call_args = mock_db_manager.cur.execute.call_args_list[0]
        assert "pg_type" in str(first_call_args)
