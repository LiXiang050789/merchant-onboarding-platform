from __future__ import annotations

import pytest
from sqlalchemy import func, select

from backend.app.batch_pipeline import build_batches
from backend.app.dlq_worker import process_dlq_once
from backend.app.models import (
    Batch, BatchStatus, DLQItem, Form, FormAuditEvent, FormStatus, FormType,
    SubmissionEvent, SubmissionEventType, User,
)
from backend.app.realtime import subscribe, unsubscribe
from backend.tests.conftest import login
from backend.tests.test_batch_pipeline import make_form

pytestmark = pytest.mark.asyncio


def drain(queue):
    result = []
    while not queue.empty():
        result.append(queue.get_nowait())
    return result


async def headers(client):
    return {"Authorization": "Bearer " + await login(client, "admin@example.com", "pass-admin")}


async def audits(session, form_id):
    return list((await session.scalars(select(FormAuditEvent).where(
        FormAuditEvent.form_id == form_id,
        FormAuditEvent.event_type == "status_pipeline_changed",
    ).order_by(FormAuditEvent.id))).all())


async def published_events(session, form_id):
    return await session.scalar(select(func.count()).select_from(SubmissionEvent).where(
        SubmissionEvent.form_id == form_id,
        SubmissionEvent.event_type == SubmissionEventType.business_published,
    ))


async def test_build_groups_bulk_by_tenant_and_preserves_batch_events(client, session):
    forms = [make_form(idx, FormType.property, tenant_id="tenant_a" if idx <= 3 else "tenant_b") for idx in range(1, 7)]
    form_ids = [form.id for form in forms]
    session.add_all(forms)
    await session.commit()
    queues = {tenant: await subscribe(tenant) for tenant in ["tenant_a", "tenant_b", "tenant_other"]}
    try:
        response = await client.post('/api/v1/batches/build', headers=await headers(client), json={"capacity":1,"radius_m":3000})
        assert response.status_code == 200
        batches = response.json()['batches']
        assert len(batches) == 6
        for tenant in ["tenant_a", "tenant_b"]:
            events = drain(queues[tenant])
            bulk = [event for event in events if event.type == 'form.bulk_status_changed']
            expected = [batch['id'] for batch in batches if batch['tenant_id'] == tenant]
            assert len(bulk) == 1
            assert bulk[0].tenant_id == tenant
            assert bulk[0].payload == {"operation":"build","status":"batched","batch_ids":expected,"forms":3}
            assert len([event for event in events if event.type == 'batch.status_changed']) == 3
            assert not any(event.type == 'form.status_changed' for event in events)
        assert queues['tenant_other'].empty()
        await session.rollback()
        for form_id in form_ids:
            records = await audits(session, form_id)
            assert [(record.from_status, record.to_status, record.actor_id, record.payload_hash) for record in records] == [
                ('validated','batched','batch_pipeline','batch_pipeline'),
            ]
        second = await client.post('/api/v1/batches/build', headers=await headers(client), json={"capacity":1,"radius_m":3000})
        assert second.status_code == 200 and second.json()['total_forms'] == 0
        assert all(queue.empty() for queue in queues.values())
    finally:
        for tenant, queue in queues.items():
            unsubscribe(tenant, queue)


async def test_run_emits_one_bulk_and_idempotent_rerun_adds_no_events_or_audits(client, session):
    forms = [make_form(idx, FormType.property) for idx in (10,11)]
    form_ids = [form.id for form in forms]
    session.add_all(forms)
    await session.commit()
    auth = await headers(client)
    built = await client.post('/api/v1/batches/build', headers=auth, json={"city":"shanghai","capacity":50,"radius_m":3000})
    batch_id = built.json()['batches'][0]['id']
    queue = await subscribe('tenant_a')
    try:
        response = await client.post(f'/api/v1/batches/{batch_id}/run', headers=auth)
        assert response.status_code == 202
        events = drain(queue)
        bulk = [event for event in events if event.type == 'form.bulk_status_changed']
        assert len(bulk) == 1
        assert bulk[0].payload == {"operation":"run","batch_id":batch_id,"published":2,"failed":0}
        await session.rollback()
        assert (await session.get(Batch,batch_id)).status == BatchStatus.completed
        for form_id in form_ids:
            records = await audits(session, form_id)
            assert [(record.from_status,record.to_status) for record in records] == [('validated','batched'),('batched','published')]
            assert all(record.actor_id == 'batch_pipeline' for record in records)
            assert await published_events(session,form_id) == 1
        again = await client.post(f'/api/v1/batches/{batch_id}/run',headers=auth)
        assert again.status_code == 202 and again.json()['processed'] == 0
        assert queue.empty()
        await session.rollback()
        for form_id in form_ids:
            assert len(await audits(session,form_id)) == 2
            assert await published_events(session,form_id) == 1
    finally:
        unsubscribe('tenant_a',queue)


@pytest.mark.parametrize('invalid_payload',[False,True])
async def test_failure_audit_and_dlq_recovery_preserve_prior_records(client, session, invalid_payload):
    bad = make_form(20,FormType.product,payload_extra={"force_dlq_stage":"product_pipeline"})
    if invalid_payload:
        bad.payload = {}
    untouched = make_form(21,FormType.product)
    bad_id, untouched_id = bad.id, untouched.id
    session.add_all([bad,untouched])
    await session.commit()
    auth = await headers(client)
    built = await client.post('/api/v1/batches/build',headers=auth,json={"city":"shanghai","capacity":50,"radius_m":3000})
    batch_id = built.json()['batches'][0]['id']
    queue = await subscribe('tenant_a')
    try:
        response = await client.post(f'/api/v1/batches/{batch_id}/run',headers=auth)
        assert response.status_code == 202
        bulk = [event for event in drain(queue) if event.type == 'form.bulk_status_changed']
        assert len(bulk) == 1 and bulk[0].payload == {"operation":"run","batch_id":batch_id,"published":0,"failed":1}
        await session.rollback()
        records = await audits(session,bad_id)
        assert [(record.from_status,record.to_status) for record in records] == [('validated','batched'),('batched','failed')]
        assert len(await audits(session,untouched_id)) == 1
        preserved = [(record.id,record.from_status,record.to_status,record.actor_id) for record in records]
        form = await session.get(Form,bad_id)
        form.payload = {"product_name":"recovered","sku":"recovered"}
        item = await session.scalar(select(DLQItem).where(DLQItem.form_id==bad_id))
        await session.commit()
        assert await process_dlq_once(session,now=item.next_retry_at) == 1
        records = await audits(session,bad_id)
        assert [(record.id,record.from_status,record.to_status,record.actor_id) for record in records[:2]] == preserved
        assert (records[-1].from_status,records[-1].to_status,records[-1].actor_id,records[-1].payload_hash) == ('failed','published','dlq_worker','dlq_worker')
        assert await published_events(session,bad_id) == 1
        assert len(records) == 3
        assert await process_dlq_once(session,now=item.next_retry_at) == 0
        assert len(await audits(session,bad_id)) == 3
    finally:
        unsubscribe('tenant_a',queue)


async def test_build_rollback_rolls_back_audits_together(seeded_session):
    session = seeded_session
    form = make_form(30,FormType.property)
    session.add(form)
    await session.commit()
    actor = await session.get(User,'admin')
    await build_batches(session,actor,city='shanghai',form_type=None,capacity=50,radius_m=3000)
    assert len(await audits(session,form.id)) == 1
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(FormAuditEvent)) == 0
    assert await session.scalar(select(func.count()).select_from(Batch)) == 0
    assert (await session.get(Form,'form_batch_030')).status == FormStatus.validated
