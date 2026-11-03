from alembic import command
from alembic.config import Config

from .config import ROOT


def upgrade_schema(engine):
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
