import pytest
from unittest.mock import MagicMock, patch
import psycopg

from data_pipeline.tools.database_manager import DatabaseManager


@pytest.fixture
def mock_connection():
    """Create a mock psycopg connection and cursor."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn, mock_cur


@pytest.fixture
def db_manager():
    """Create a DatabaseManager instance without connecting."""
    return DatabaseManager(
        db_name="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port="5432"
    )


class TestConnect:
    def test_connect_success(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection

        with patch('data_pipeline.tools.database_manager.psycopg.connect', return_value=mock_conn):
            db_manager.connect()

        assert db_manager.conn == mock_conn
        assert db_manager.cur == mock_cur

    def test_connect_failure_bad_credentials(self, db_manager):
        with patch('data_pipeline.tools.database_manager.psycopg.connect') as mock_connect:
            mock_connect.side_effect = psycopg.OperationalError("connection failed")

            with pytest.raises(RuntimeError, match="Please check your connection details"):
                db_manager.connect()

    def test_connect_failure_generic_error(self, db_manager):
        with patch('data_pipeline.tools.database_manager.psycopg.connect') as mock_connect:
            mock_connect.side_effect = psycopg.Error("generic error")

            with pytest.raises(RuntimeError, match="An error occurred"):
                db_manager.connect()


class TestClose:
    def test_close_connection(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        db_manager.close()

        mock_cur.close.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_close_when_not_connected(self, db_manager):
        # Should not raise when conn/cur are None
        db_manager.close()


class TestInsertRow:
    def test_insert_row_success(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        db_manager.insert_row("test_table", ["col1", "col2"], ["val1", "val2"])

        mock_cur.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_insert_row_empty_data_raises(self, db_manager):
        with pytest.raises(ValueError, match="Data list is empty"):
            db_manager.insert_row("test_table", ["col1"], [])

    def test_insert_row_empty_table_name_raises(self, db_manager):
        with pytest.raises(ValueError, match="Table name is empty"):
            db_manager.insert_row("", ["col1"], ["val1"])

    def test_insert_row_empty_columns_raises(self, db_manager):
        with pytest.raises(ValueError, match="Column names list is empty"):
            db_manager.insert_row("test_table", [], ["val1"])

    def test_insert_row_mismatched_columns_raises(self, db_manager):
        with pytest.raises(ValueError, match="Column names count does not match"):
            db_manager.insert_row("test_table", ["col1", "col2"], ["val1"])


class TestInsertRowAndReturnId:
    def test_insert_row_and_return_id(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.fetchone.return_value = (42,)
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        result = db_manager.insert_row_and_return_id("test_table", ["col1"], ["val1"])

        assert result == 42
        mock_cur.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_insert_row_and_return_id_on_error(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.execute.side_effect = psycopg.Error("insert failed")
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        result = db_manager.insert_row_and_return_id("test_table", ["col1"], ["val1"])

        assert result == -1


class TestInsertRows:
    def test_insert_rows_batch(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        rows = [("val1", "val2"), ("val3", "val4"), ("val5", "val6")]

        db_manager.insert_rows("test_table", ["col1", "col2"], rows)

        mock_cur.executemany.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_insert_rows_empty_raises(self, db_manager):
        with pytest.raises(ValueError, match="Rows list is empty"):
            db_manager.insert_rows("test_table", ["col1"], [])

    def test_insert_rows_empty_table_name_raises(self, db_manager):
        with pytest.raises(ValueError, match="Table name is empty"):
            db_manager.insert_rows("", ["col1"], [("val1",)])

    def test_insert_rows_empty_columns_raises(self, db_manager):
        with pytest.raises(ValueError, match="Column names list is empty"):
            db_manager.insert_rows("test_table", [], [("val1",)])

    def test_insert_rows_rollback_on_error(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.executemany.side_effect = psycopg.Error("batch insert failed")
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        with pytest.raises(psycopg.Error):
            db_manager.insert_rows("test_table", ["col1"], [("val1",)])

        mock_conn.rollback.assert_called_once()


class TestExecuteQuery:
    def test_execute_query_select(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.fetchall.return_value = [("row1",), ("row2",)]
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        results = db_manager.execute_query("SELECT * FROM test_table")

        assert results == [("row1",), ("row2",)]
        mock_cur.execute.assert_called_once_with("SELECT * FROM test_table")

    def test_execute_query_on_error(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.execute.side_effect = psycopg.Error("query failed")
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        results = db_manager.execute_query("SELECT * FROM test_table")

        assert results == []


class TestUpdateRowsByIds:
    def test_update_rows_by_ids_success(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        db_manager.update_rows_by_ids("albums", "work_status", "completed", [1, 2, 3])

        mock_cur.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_update_rows_by_ids_empty_ids_skips(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        db_manager.update_rows_by_ids("albums", "work_status", "completed", [])

        mock_cur.execute.assert_not_called()

    def test_update_rows_by_ids_empty_table_raises(self, db_manager):
        with pytest.raises(ValueError, match="Table name is empty"):
            db_manager.update_rows_by_ids("", "col", "val", [1])

    def test_update_rows_by_ids_empty_column_raises(self, db_manager):
        with pytest.raises(ValueError, match="Column name is empty"):
            db_manager.update_rows_by_ids("table", "", "val", [1])

    def test_update_rows_by_ids_rollback_on_error(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.execute.side_effect = psycopg.Error("update failed")
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        db_manager.update_rows_by_ids("albums", "work_status", "completed", [1])

        mock_conn.rollback.assert_called_once()


class TestUpsertRow:
    def test_upsert_row_success(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.rowcount = 1
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        db_manager.upsert_row("test_table", ["col1", "col2"], ["val1", "val2"], "col1")

        mock_cur.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_upsert_row_returns_true_on_insert(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.rowcount = 1
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        result = db_manager.upsert_row("test_table", ["col1"], ["val1"], "col1")

        assert result is True

    def test_upsert_row_returns_false_on_conflict(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.rowcount = 0
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        result = db_manager.upsert_row("test_table", ["col1"], ["val1"], "col1")

        assert result is False

    def test_upsert_row_empty_data_raises(self, db_manager):
        with pytest.raises(ValueError, match="Data list is empty"):
            db_manager.upsert_row("test_table", ["col1"], [], "col1")

    def test_upsert_row_empty_table_name_raises(self, db_manager):
        with pytest.raises(ValueError, match="Table name is empty"):
            db_manager.upsert_row("", ["col1"], ["val1"], "col1")

    def test_upsert_row_empty_columns_raises(self, db_manager):
        with pytest.raises(ValueError, match="Column names list is empty"):
            db_manager.upsert_row("test_table", [], ["val1"], "col1")

    def test_upsert_row_mismatched_columns_raises(self, db_manager):
        with pytest.raises(ValueError, match="Column names count does not match"):
            db_manager.upsert_row("test_table", ["col1", "col2"], ["val1"], "col1")

    def test_upsert_row_empty_conflict_column_raises(self, db_manager):
        with pytest.raises(ValueError, match="Conflict column is empty"):
            db_manager.upsert_row("test_table", ["col1"], ["val1"], "")


class TestUpsertRowAndReturnId:
    def test_upsert_row_and_return_id_new_row(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.fetchone.return_value = (42,)
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        result = db_manager.upsert_row_and_return_id(
            "test_table", ["col1", "col2"], ["val1", "val2"], "col1"
        )

        assert result == 42
        mock_conn.commit.assert_called_once()

    def test_upsert_row_and_return_id_existing_row(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        # First fetchone returns None (conflict), second returns existing ID
        mock_cur.fetchone.side_effect = [None, (99,)]
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        result = db_manager.upsert_row_and_return_id(
            "test_table", ["col1", "col2"], ["val1", "val2"], "col1"
        )

        assert result == 99
        assert mock_cur.execute.call_count == 2

    def test_upsert_row_and_return_id_empty_data_raises(self, db_manager):
        with pytest.raises(ValueError, match="Data list is empty"):
            db_manager.upsert_row_and_return_id("test_table", ["col1"], [], "col1")

    def test_upsert_row_and_return_id_empty_conflict_column_raises(self, db_manager):
        with pytest.raises(ValueError, match="Conflict column is empty"):
            db_manager.upsert_row_and_return_id("test_table", ["col1"], ["val1"], "")

    def test_upsert_row_and_return_id_conflict_column_not_in_columns_raises(self, db_manager):
        with pytest.raises(ValueError, match="Conflict column 'col2' not found"):
            db_manager.upsert_row_and_return_id(
                "test_table", ["col1"], ["val1"], "col2"
            )

    def test_upsert_row_and_return_id_on_error(self, db_manager, mock_connection):
        mock_conn, mock_cur = mock_connection
        mock_cur.execute.side_effect = psycopg.Error("upsert failed")
        db_manager.conn = mock_conn
        db_manager.cur = mock_cur

        result = db_manager.upsert_row_and_return_id(
            "test_table", ["col1"], ["val1"], "col1"
        )

        assert result == -1
