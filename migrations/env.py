from alembic import context

from tender_enricher.config import Settings
from tender_enricher.db.models import Base
from tender_enricher.db.session import make_engine


def run_migrations() -> None:
    config = context.config
    if context.is_offline_mode():
        context.configure(
            url=Settings().database_url,
            target_metadata=Base.metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = make_engine(Settings().database_url)
        try:
            with engine.connect() as connection:
                context.configure(connection=connection, target_metadata=Base.metadata)
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            engine.dispose()


run_migrations()
