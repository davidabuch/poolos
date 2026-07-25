from datetime import datetime, timezone

from poolos import EventBus, PoolEvent


def test_topic_wildcard_and_unsubscribe() -> None:
    bus = EventBus()
    direct = []
    wildcard = []
    unsubscribe = bus.subscribe("test", direct.append)
    bus.subscribe("*", wildcard.append)
    event = PoolEvent("test", datetime.now(timezone.utc), "unit-test")

    bus.publish(event)
    unsubscribe()
    bus.publish(event)

    assert direct == [event]
    assert wildcard == [event, event]
