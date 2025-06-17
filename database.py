from typing import Dict, List, Optional, Any
from pymongo import MongoClient
from datetime import datetime
from src.virtualization.digital_replica.schema_registry import SchemaRegistry


class Database:
    def __init__(
        self, connection_string: str, db_name: str, schema_registry: SchemaRegistry
    ):
        self.connection_string = connection_string
        self.db_name = db_name
        self.schema_registry = schema_registry
        self.client = None
        self.db = None

    def connect(self) -> None:
        try:
            self.client = MongoClient(self.connection_string)
            self.db = self.client[self.db_name]
        except Exception as e:
            raise ConnectionError(f"Failed to connect to MongoDB: {str(e)}")

    def disconnect(self) -> None:
        if self.client:
            self.client.close()
            self.client = None
            self.db = None

    def is_connected(self) -> bool:
        return self.client is not None and self.db is not None

    def wipe_test_db(self) -> bool:
        return self.client.drop_database(self.db_name)

