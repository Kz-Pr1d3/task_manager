from src.core.sse_hub import SSEHub


async def test__publish_to_user__delivers_to_all_queues():
    hub = SSEHub()
    first_tab = await hub.subscribe(user_id=7)
    second_tab = await hub.subscribe(user_id=7)

    await hub.publish_to_user(
        user_id=7,
        message={"type": "notification.invalidate"},
    )

    assert (await first_tab.get())["type"] == "notification.invalidate"
    assert (await second_tab.get())["type"] == "notification.invalidate"


async def test__publish_to_user__other_user_not_notified():
    hub = SSEHub()
    own = await hub.subscribe(user_id=7)
    other = await hub.subscribe(user_id=8)

    await hub.publish_to_user(
        user_id=7,
        message={"type": "notification.invalidate"},
    )

    assert (await own.get())["type"] == "notification.invalidate"
    assert other.empty()
    assert await hub.connection_count() == 2


async def test__unsubscribe__removes_queue():
    hub = SSEHub()
    queue = await hub.subscribe(user_id=7)
    await hub.unsubscribe(user_id=7, queue=queue)

    assert await hub.connection_count() == 0

    await hub.publish_to_user(
        user_id=7,
        message={"type": "notification.invalidate"},
    )
    assert queue.empty()
