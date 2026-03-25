import psycopg
from psycopg import sql

class DatabaseManager:
    def __init__(self, db_name: str, user: str, password: str, host: str, port: str):
        self.conn = None
        self.cur = None
        self.db_name = db_name
        self.user = user
        self.password = password
        self.host = host
        self.port = port

    def connect(self) -> None:
        try:
            # Establish a connection to the database, no sql command is executed here -> no sql injection risk
            self.conn = psycopg.connect(
                dbname=self.db_name,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port
            )
            self.cur = self.conn.cursor()
            print("Connected to the database successfully.")
        except psycopg.OperationalError as e:
            print(f"Connection failed: {e}")
            raise RuntimeError("Please check your connection details and ensure PostgreSQL is running.")
        except psycopg.Error as e:
            raise RuntimeError(f"An error occurred: {e}")

    def close(self) -> None:
        # Close the cursor and connection if they are open, no sql command is executed here -> no sql injection risk
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
            print("Database connection closed.")

    def insert_row(self, table_name: str, column_names: list[str], data: list) -> None:
        if not data:
            raise ValueError("Data list is empty. Cannot insert row without data.")
        if not table_name:
            raise ValueError("Table name is empty. Cannot insert row without a table name.")
        if not column_names:
            raise ValueError("Column names list is empty. Cannot insert row without column names.")
        if len(column_names) != len(data):
            raise ValueError("Column names count does not match data count.")
        
        query = sql.SQL('INSERT INTO {tableName} ({columnNames}) VALUES ({placeholders});').format(
            tableName = sql.Identifier(table_name), 
            columnNames = sql.SQL(', ').join(sql.Identifier(col) for col in column_names),
            placeholders = sql.SQL(', ').join(sql.Placeholder() for _ in data)
        )
        
        try:
            self.cur.execute(query, data)
            self.conn.commit()
            print(f"Inserted row into {table_name} successfully.")
        except psycopg.Error as e:
            print(f"An error inserting row occurred: {e}")
    
    def insert_row_and_return_id(self, table_name: str, column_names: list[str], data: list) -> int:
        if not data:
            raise ValueError("Data list is empty. Cannot insert row without data.")
        if not table_name:
            raise ValueError("Table name is empty. Cannot insert row without a table name.")
        if not column_names:
            raise ValueError("Column names list is empty. Cannot insert row without column names.")
        if len(column_names) != len(data):
            raise ValueError("Column names count does not match data count.")
        
        query = sql.SQL('INSERT INTO {tableName} ({columnNames}) VALUES ({placeholders}) RETURNING id;').format(
            tableName = sql.Identifier(table_name), 
            columnNames = sql.SQL(', ').join(sql.Identifier(col) for col in column_names),
            placeholders = sql.SQL(', ').join(sql.Placeholder() for _ in data)
        )
        
        try:
            self.cur.execute(query, data)
            returned_id = self.cur.fetchone()[0]
            self.conn.commit()
            print(f"Inserted row into {table_name} successfully with ID {returned_id}.")
            return returned_id
        except psycopg.Error as e:
            print(f"An error inserting row occurred: {e}")
            return -1

    def execute_query(self, query: str) -> list:
        try:
            self.cur.execute(query)
            results = self.cur.fetchall()
            self.conn.commit()
            return results
        except psycopg.Error as e:
            self.conn.rollback()
            print(f"An error occurred: {e}")
            return []

    def update_rows_by_ids(self, table_name: str, column_name: str, value: str, ids: list[int]) -> None:
        """Update a column value for multiple rows by their IDs.

        Args:
            table_name: Name of the table to update
            column_name: Name of the column to update
            value: The new value to set
            ids: List of row IDs to update
        """
        if not ids:
            return
        if not table_name:
            raise ValueError("Table name is empty.")
        if not column_name:
            raise ValueError("Column name is empty.")

        query = sql.SQL('UPDATE {table} SET {column} = %s WHERE id = ANY(%s)').format(
            table=sql.Identifier(table_name),
            column=sql.Identifier(column_name)
        )

        try:
            self.cur.execute(query, [value, ids])
            self.conn.commit()
            print(f"Updated {self.cur.rowcount} rows in {table_name}.")
        except psycopg.Error as e:
            self.conn.rollback()
            print(f"An error updating rows occurred: {e}")

    def insert_rows(self, table_name: str, column_names: list[str], rows: list[tuple]) -> None:
        """Batch insert multiple rows into a table.

        Args:
            table_name: Name of the table to insert into
            column_names: List of column names
            rows: List of tuples, each tuple containing values for one row
        """
        if not rows:
            raise ValueError("Rows list is empty. Cannot insert without data.")
        if not table_name:
            raise ValueError("Table name is empty. Cannot insert without a table name.")
        if not column_names:
            raise ValueError("Column names list is empty. Cannot insert without column names.")

        query = sql.SQL('INSERT INTO {table} ({columns}) VALUES ({placeholders})').format(
            table=sql.Identifier(table_name),
            columns=sql.SQL(', ').join(sql.Identifier(col) for col in column_names),
            placeholders=sql.SQL(', ').join(sql.Placeholder() for _ in column_names)
        )

        try:
            self.cur.executemany(query, rows)
            self.conn.commit()
            print(f"Inserted {len(rows)} rows into {table_name} successfully.")
        except psycopg.Error as e:
            self.conn.rollback()
            print(f"An error inserting rows occurred: {e}")
            raise

    def insert_rows_ignore_conflicts(self, table_name: str, column_names: list[str], rows: list[tuple]) -> None:
        """Batch insert rows, silently skipping any that violate unique constraints.

        Args:
            table_name: Name of the table to insert into
            column_names: List of column names
            rows: List of tuples, each tuple containing values for one row
        """
        if not rows:
            raise ValueError("Rows list is empty. Cannot insert without data.")
        if not table_name:
            raise ValueError("Table name is empty. Cannot insert without a table name.")
        if not column_names:
            raise ValueError("Column names list is empty. Cannot insert without column names.")

        query = sql.SQL(
            'INSERT INTO {table} ({columns}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
        ).format(
            table=sql.Identifier(table_name),
            columns=sql.SQL(', ').join(sql.Identifier(col) for col in column_names),
            placeholders=sql.SQL(', ').join(sql.Placeholder() for _ in column_names)
        )

        try:
            self.cur.executemany(query, rows)
            self.conn.commit()
            print(f"Inserted {self.cur.rowcount} rows into {table_name} (duplicates skipped).")
        except psycopg.Error as e:
            self.conn.rollback()
            print(f"An error inserting rows occurred: {e}")
            raise

    def upsert_row(self, table_name: str, column_names: list[str], data: list,
                   conflict_column: str) -> bool:
        """Insert a row, or do nothing if conflict on unique column.

        Args:
            table_name: Name of the table to insert into
            column_names: List of column names
            data: List of values corresponding to column_names
            conflict_column: The column with UNIQUE constraint to check for conflicts

        Returns:
            True if a row was inserted, False if conflict (duplicate) or error
        """
        if not data:
            raise ValueError("Data list is empty. Cannot insert row without data.")
        if not table_name:
            raise ValueError("Table name is empty. Cannot insert row without a table name.")
        if not column_names:
            raise ValueError("Column names list is empty. Cannot insert row without column names.")
        if len(column_names) != len(data):
            raise ValueError("Column names count does not match data count.")
        if not conflict_column:
            raise ValueError("Conflict column is empty. Cannot upsert without a conflict column.")

        query = sql.SQL(
            'INSERT INTO {table} ({columns}) VALUES ({placeholders}) '
            'ON CONFLICT ({conflict}) DO NOTHING;'
        ).format(
            table=sql.Identifier(table_name),
            columns=sql.SQL(', ').join(sql.Identifier(col) for col in column_names),
            placeholders=sql.SQL(', ').join(sql.Placeholder() for _ in data),
            conflict=sql.Identifier(conflict_column)
        )

        try:
            self.cur.execute(query, data)
            # rowcount is 1 if inserted, 0 if conflict (DO NOTHING)
            # Must capture before commit() as commit may reset rowcount
            was_inserted = self.cur.rowcount > 0
            self.conn.commit()
            return was_inserted
        except psycopg.Error as e:
            self.conn.rollback()
            print(f"An error upserting row occurred: {e}")
            return False

    def upsert_row_and_return_id(self, table_name: str, column_names: list[str], data: list,
                                  conflict_column: str) -> int:
        """Insert a row and return its ID, or return existing ID if conflict.

        Args:
            table_name: Name of the table to insert into
            column_names: List of column names
            data: List of values corresponding to column_names
            conflict_column: The column with UNIQUE constraint to check for conflicts

        Returns:
            The ID of the inserted or existing row, or -1 on error
        """
        if not data:
            raise ValueError("Data list is empty. Cannot insert row without data.")
        if not table_name:
            raise ValueError("Table name is empty. Cannot insert row without a table name.")
        if not column_names:
            raise ValueError("Column names list is empty. Cannot insert row without column names.")
        if len(column_names) != len(data):
            raise ValueError("Column names count does not match data count.")
        if not conflict_column:
            raise ValueError("Conflict column is empty. Cannot upsert without a conflict column.")

        # Find the index of the conflict column to get its value
        try:
            conflict_idx = column_names.index(conflict_column)
            conflict_value = data[conflict_idx]
        except ValueError:
            raise ValueError(f"Conflict column '{conflict_column}' not found in column_names.")

        query = sql.SQL(
            'INSERT INTO {table} ({columns}) VALUES ({placeholders}) '
            'ON CONFLICT ({conflict}) DO NOTHING '
            'RETURNING id;'
        ).format(
            table=sql.Identifier(table_name),
            columns=sql.SQL(', ').join(sql.Identifier(col) for col in column_names),
            placeholders=sql.SQL(', ').join(sql.Placeholder() for _ in data),
            conflict=sql.Identifier(conflict_column)
        )

        try:
            self.cur.execute(query, data)
            result = self.cur.fetchone()
            self.conn.commit()

            if result:
                # Row was inserted, return new ID
                print(f"{result[0]} inserted succesfully into database.")
                return result[0]
            else:
                # Conflict occurred, fetch existing ID
                select_query = sql.SQL(
                    'SELECT id FROM {table} WHERE {conflict} = %s;'
                ).format(
                    table=sql.Identifier(table_name),
                    conflict=sql.Identifier(conflict_column)
                )
                self.cur.execute(select_query, [conflict_value])
                existing = self.cur.fetchone()
                if existing:
                    return existing[0]
                return -1
        except psycopg.Error as e:
            print(f"An error upserting row occurred: {e}")
            return -1