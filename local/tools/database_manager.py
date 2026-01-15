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
            return results
        except psycopg.Error as e:
            print(f"An error occurred: {e}")
            return []

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