from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

BASE_DIR = Path(__file__).resolve().parent


def migrate_database() -> None:
    command.upgrade(Config(str(BASE_DIR / "alembic.ini")), "head")


if __name__ == "__main__":
    migrate_database()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
