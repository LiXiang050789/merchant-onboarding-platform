from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.db import Base, get_session
from backend.app.main import app
from backend.app.models import Tenant, TenantStatus, User, UserRole
from backend.app.security import hash_password


TEST_DSN = "mysql+asyncmy://merchant:merchant_pass@127.0.0.1:3306/merchant_test"


@pytest.fixture
async def engine():
    admin_engine = create_async_engine("mysql+asyncmy://root:merchant_root@127.0.0.1:3306/mysql", poolclass=NullPool)
    async with admin_engine.begin() as conn:
        await conn.execute(text("CREATE DATABASE IF NOT EXISTS merchant_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
        await conn.execute(text("GRANT ALL PRIVILEGES ON merchant_test.* TO 'merchant'@'%'"))
    await admin_engine.dispose()

    test_engine = create_async_engine(TEST_DSN, pool_pre_ping=True, poolclass=NullPool)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())
        await session.commit()
        yield session


@pytest.fixture
async def seeded_session(session: AsyncSession) -> AsyncSession:
    session.add_all(
        [
            Tenant(id="tenant_a", name="Tenant A", status=TenantStatus.active),
            Tenant(id="tenant_b", name="Tenant B", status=TenantStatus.active),
            User(
                id="user_a",
                tenant_id="tenant_a",
                email="a@example.com",
                password_hash=hash_password("pass-a", salt="salt-a"),
                role=UserRole.merchant,
            ),
            User(
                id="user_b",
                tenant_id="tenant_b",
                email="b@example.com",
                password_hash=hash_password("pass-b", salt="salt-b"),
                role=UserRole.merchant,
            ),
            User(
                id="operator_shanghai",
                tenant_id="tenant_a",
                email="op@example.com",
                password_hash=hash_password("pass-op", salt="salt-op"),
                role=UserRole.operator,
                region_code="shanghai",
            ),
            User(
                id="admin",
                tenant_id="tenant_a",
                email="admin@example.com",
                password_hash=hash_password("pass-admin", salt="salt-admin"),
                role=UserRole.admin,
            ),
        ]
    )
    await session.commit()
    return session


@pytest.fixture
async def client(engine, seeded_session) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]
