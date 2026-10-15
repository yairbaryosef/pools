"""Idempotent local SQLite bootstrap."""

from atlas.database import SQLiteDatabase, SQLiteSettings


def bootstrap() -> None:
    database = SQLiteDatabase(SQLiteSettings.from_env())
    try:
        database.ensure_indexes()
    finally:
        database.close()


if __name__ == "__main__":
    bootstrap()
