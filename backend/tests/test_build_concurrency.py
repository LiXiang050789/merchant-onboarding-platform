from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from backend.app.models import BatchItem, Form, FormStatus, FormType
from backend.tests.conftest import login
from backend.tests.test_batch_pipeline import make_form


@pytest.mark.asyncio
async def test_concurrent_builds_preserve_unique_membership_three_rounds(client, session):
    token = await login(client, "admin@example.com", "pass-admin")
    headers = {"Authorization": f"Bearer {token}"}
    members_per_round = 8
    for round_index in range(3):
        forms = [make_form(round_index * 10 + idx, FormType.merchant_info) for idx in range(1, members_per_round + 1)]
        form_ids = {form.id for form in forms}
        session.add_all(forms)
        await session.commit()

        responses = await asyncio.gather(*(
            client.post("/api/v1/batches/build", headers=headers, json={"city": "shanghai", "capacity": 50, "radius_m": 3000})
            for _ in range(2)
        ))
        assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
        assert sum(response.json()["total_forms"] for response in responses) == members_per_round
        assert sum(batch["item_count"] for response in responses for batch in response.json()["batches"]) == members_per_round

        await session.rollback()
        items = (await session.execute(select(BatchItem))).scalars().all()
        member_ids = [item.form_id for item in items]
        assert len(member_ids) == len(set(member_ids)) == (round_index + 1) * members_per_round
        assert {item.form_id for item in items if item.form_id in form_ids} == form_ids
        memberships = {item.form_id: item.batch_id for item in items}
        persisted = (await session.execute(select(Form.id, Form.status, Form.batch_id).where(Form.id.in_(form_ids)))).all()
        assert len(persisted) == members_per_round
        assert all(status == FormStatus.batched and batch_id == memberships[form_id] for form_id, status, batch_id in persisted)
        print(f"build concurrency round={round_index + 1} members={members_per_round} cumulative_unique={len(set(member_ids))}")
