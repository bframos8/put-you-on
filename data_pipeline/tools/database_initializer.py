from local.tools.database_manager import DatabaseManager
import psycopg
from psycopg import sql

class DatabaseInitializer:
    def __init__(self, database_manager: DatabaseManager):
        # Initialize DatabaseManager to handle connections, using dependency injection
        self.database_manager = database_manager
        self.conn = self.database_manager.conn
        self.cur = self.database_manager.cur
        
    def create_table(self, table_name: str, column_names:list[str]) -> None:
        # Create table with the given columns, sql command is executed here -> sql injection risk, use psycopg.sql queries to avoid it
        if not column_names:
            raise ValueError("Columns list is empty. Cannot create table without columns.")
        if not table_name:
            raise ValueError("Table name is empty. Cannot create table without a name.")
        
        query = sql.SQL("CREATE TABLE IF NOT EXISTS {tableName} ({columnNames})"
                    ).format(
                        tableName = sql.Identifier(table_name), 
                        columnNames = sql.SQL(", ").join(sql.Identifier(col) for col in column_names))
        
        try:
            self.cur.execute(query)
            self.conn.commit()
            print(f"Table '{table_name}' created successfully.")
        except psycopg.Error as e:
            self.conn.rollback()
            raise ValueError(f"An error creating table occurred: {e}")
    
    def create_type(self, type_name: str, values: list[str]) -> None:
        if not values:
            raise ValueError("Values list is empty. Cannot create type without values.")
        if not type_name:
            raise ValueError("Type name is empty. Cannot create type without a name.")

        # Check if type already exists
        self.cur.execute(
            "SELECT 1 FROM pg_type WHERE typname = %s",
            (type_name,)
        )
        if self.cur.fetchone():
            print(f"Type '{type_name}' already exists, skipping.")
            return

        enum_values = sql.SQL(", ").join(
            sql.Literal(value) for value in values
            )
        query = sql.SQL('CREATE TYPE {typeName} AS ENUM ({enumValues});'
                        ).format(
                            typeName = sql.Identifier(type_name),
                            enumValues = enum_values)

        try:
            self.cur.execute(query)
            self.conn.commit()
            print(f"Type '{type_name}' created successfully.")
        except psycopg.Error as e:
            self.conn.rollback()
            raise ValueError(f"An error creating type occurred: {e}")