import pytest
from unittest.mock import Mock, MagicMock, patch
import psycopg

from local.tools.database_manager import DatabaseManager


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

        with patch('local.tools.database_manager.psycopg.connect', return_value=mock_conn):
            db_manager.connect()

        assert db_manager.conn == mock_conn
        assert db_manager.cur == mock_cur

    def test_connect_failure_bad_credentials(self, db_manager):
        with patch('local.tools.database_manager.psycopg.connect') as mock_connect:
            mock_connect.side_effect = psycopg.OperationalError("connection failed")

            with pytest.raises(RuntimeError, match="Please check your connection details"):
                db_manager.connect()

    def test_connect_failure_generic_error(self, db_manager):
        with patch('local.tools.database_manager.psycopg.connect') as mock_connect:
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

        rows = [
            ("val1", "val2"),
            ("val3", "val4"),
            ("val5", "val6"),
        ]

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
