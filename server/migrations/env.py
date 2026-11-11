from alembic import context
from techo.models import Base

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    from techo.config import Settings
    from techo.database import Database

    database = Database(Settings.from_env())
    try:
        with database.engine.connect() as connection:
            run(connection)
    finally:
        database.close()
