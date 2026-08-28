"""
Database configuration and session management.
Uses SQLAlchemy with asyncpg driver for async PostgreSQL operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
from api.config import settings
from logger import setup_logger

logger = setup_logger(__name__)

# Create async engine for main API (with connection pooling for performance)
try:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,  # Set to True for SQL query logging
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    logger.info("Database engine created successfully")
except Exception as e:
    logger.error(f"Failed to create database engine: {e}", exc_info=True)
    raise

# Create async engine for background tasks (with NullPool to avoid event loop issues)
try:
    background_engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        poolclass=NullPool,  # No pooling to prevent cross-event-loop issues
    )
    logger.info("Background task engine created successfully")
except Exception as e:
    logger.error(f"Failed to create background task engine: {e}", exc_info=True)
    raise

# Create async session factory for main API
try:
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    logger.info("Database session factory created successfully")
except Exception as e:
    logger.error(f"Failed to create session factory: {e}", exc_info=True)
    raise

# Create async session factory for background tasks
try:
    BackgroundSessionLocal = async_sessionmaker(
        background_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    logger.info("Background task session factory created successfully")
except Exception as e:
    logger.error(f"Failed to create background task session factory: {e}", exc_info=True)
    raise

# Base class for SQLAlchemy models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """
    Dependency for getting async database sessions.

    Usage in FastAPI endpoints:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    session = None
    try:
        session = AsyncSessionLocal()
        logger.debug("Database session created")
        yield session
        await session.commit()
        logger.debug("Database transaction committed")
    except SQLAlchemyError as e:
        logger.error(f"Database error in session: {e}", exc_info=True)
        if session:
            await session.rollback()
            logger.debug("Database transaction rolled back")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in database session: {e}", exc_info=True)
        if session:
            await session.rollback()
            logger.debug("Database transaction rolled back")
        raise
    finally:
        if session:
            await session.close()
            logger.debug("Database session closed")


async def init_db():
    """
    Initialize database (create tables if needed).
    Note: In production, tables are created manually by client.
    This is here for development/testing purposes only.
    """
    logger.info("Initializing database")
    try:
        async with engine.begin() as conn:
            # await conn.run_sync(Base.metadata.create_all)
            pass  # Tables are created manually per client requirement
        logger.info("Database initialization completed")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        raise
