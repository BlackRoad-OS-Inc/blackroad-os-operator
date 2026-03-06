# BlackRoad OS - PostgreSQL Database
# Core relational storage with pgvector support
#
# @blackroad_name: PostgreSQL Database
# @operator: alexa.operator.v1

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

try:
    import asyncpg
    from asyncpg import Pool, Connection
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False
    asyncpg = None
    Pool = None
    Connection = None


@dataclass
class DatabaseConfig:
    """Database configuration."""

    host: str = "localhost"
    port: int = 5432
    database: str = "blackroad"
    user: str = "blackroad"
    password: str = ""
    min_connections: int = 5
    max_connections: int = 20
    ssl: bool = False

    @classmethod
    def from_url(cls, url: str) -> DatabaseConfig:
        """Parse DATABASE_URL into config."""
        # postgresql://user:pass@host:port/database
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return cls(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            database=parsed.path.lstrip("/") or "blackroad",
            user=parsed.username or "blackroad",
            password=parsed.password or "",
            ssl="sslmode=require" in url,
        )

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """Load config from environment."""
        url = os.getenv("DATABASE_URL")
        if url:
            return cls.from_url(url)
        return cls(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            database=os.getenv("PGDATABASE", "blackroad"),
            user=os.getenv("PGUSER", "blackroad"),
            password=os.getenv("PGPASSWORD", ""),
        )


class Database:
    """Async PostgreSQL database interface."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_env()
        self._pool: Optional[Pool] = None

    async def connect(self) -> None:
        """Initialize connection pool."""
        if not HAS_ASYNCPG:
            raise RuntimeError("asyncpg is not installed. Install with: pip install asyncpg")

        if self._pool is not None:
            return

        self._pool = await asyncpg.create_pool(
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
            user=self.config.user,
            password=self.config.password,
            min_size=self.config.min_connections,
            max_size=self.config.max_connections,
            ssl=self.config.ssl,
        )

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Connection]:
        """Get a connection from the pool."""
        if not self._pool:
            await self.connect()

        async with self._pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Connection]:
        """Start a transaction."""
        async with self.connection() as conn:
            async with conn.transaction():
                yield conn

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query."""
        async with self.connection() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> List[Dict[str, Any]]:
        """Fetch multiple rows."""
        async with self.connection() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def fetchrow(self, query: str, *args: Any) -> Optional[Dict[str, Any]]:
        """Fetch a single row."""
        async with self.connection() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Fetch a single value."""
        async with self.connection() as conn:
            return await conn.fetchval(query, *args)

    async def run_migrations(self, migrations_path: str = "migrations") -> None:
        """Run database migrations."""
        from pathlib import Path

        migrations_dir = Path(migrations_path)
        if not migrations_dir.exists():
            return

        # Get applied migrations
        await self.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT NOW()
            )
        """)

        applied = await self.fetch("SELECT name FROM _migrations")
        applied_names = {row["name"] for row in applied}

        # Get migration files
        migration_files = sorted(migrations_dir.glob("*.sql"))

        for migration_file in migration_files:
            if migration_file.name in applied_names:
                continue

            print(f"Applying migration: {migration_file.name}")
            sql = migration_file.read_text()

            async with self.transaction() as conn:
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (name) VALUES ($1)",
                    migration_file.name,
                )

    async def health_check(self) -> Dict[str, Any]:
        """Check database health."""
        try:
            result = await self.fetchval("SELECT 1")
            pool_size = self._pool.get_size() if self._pool else 0
            pool_free = self._pool.get_idle_size() if self._pool else 0

            return {
                "status": "healthy",
                "connected": result == 1,
                "pool_size": pool_size,
                "pool_free": pool_free,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


# Global database instance
_database: Optional[Database] = None


async def get_database() -> Database:
    """Get the global database instance."""
    global _database
    if _database is None:
        _database = Database()
        await _database.connect()
    return _database


async def close_database() -> None:
    """Close the global database connection."""
    global _database
    if _database:
        await _database.disconnect()
        _database = None
