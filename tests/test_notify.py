from app.bot.notify import AdminNotifier
from tests.fakes import FakeSender


async def test_notifier_sends_to_all_admins() -> None:
    sender = FakeSender()
    n = AdminNotifier(sender, [1, 2])
    await n.notify("salom")
    assert [s.chat_id for s in sender.sent] == [1, 2]


async def test_notifier_throttles_same_key_for_an_hour() -> None:
    t = [0.0]
    sender = FakeSender()
    n = AdminNotifier(sender, [1], clock=lambda: t[0])
    await n.notify("xato A", key="source:5")
    t[0] = 1800
    await n.notify("xato A", key="source:5")
    assert len(sender.sent) == 1
    await n.notify("boshqa", key="source:6")
    assert len(sender.sent) == 2
    t[0] = 3601
    await n.notify("xato A", key="source:5")
    assert len(sender.sent) == 3


async def test_notifier_swallows_send_errors() -> None:
    sender = FakeSender(fail_times=5)
    n = AdminNotifier(sender, [1])
    await n.notify("salom")  # xato ko'tarilmaydi
    assert sender.sent == []


async def test_notifier_masks_secrets() -> None:
    sender = FakeSender()
    n = AdminNotifier(sender, [1])
    await n.notify("token 123456789:AAH4vXk3mQ9pL2sT8wZr1yBn5cD7eF0gHiJ topildi")
    assert "AAH4vXk3" not in sender.sent[0].text
