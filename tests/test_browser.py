"""Perception and execution against a real Chromium and the local test site."""
import pytest

from karyakarta.browser import executor
from karyakarta.browser.perception import observe
from karyakarta.models import AgentAction
from karyakarta.safety.policy import parse_target


def by_label(obs, text):
    for e in obs.elements:  # an exact label wins over a partial match
        if text.lower() == e.label.lower():
            return e
    for e in obs.elements:
        if text.lower() in e.label.lower():
            return e
    raise AssertionError(f"{text!r} not found in {[e.label for e in obs.elements]}")


async def open_page(browser, site, path):
    tb = await browser.open(f"{site}/{path}")
    return tb, await observe(tb.page)


async def run(tb, obs, name, label=None, value=None, **kw):
    element = by_label(obs, label) if label else None
    action = AgentAction(action=name, mark=element.ref if element else None, value=value)
    return await executor.execute(tb.page, action, element, **kw)


# ---- perception --------------------------------------------------------------
async def test_contact_form_is_read_correctly(browser, site):
    tb, obs = await open_page(browser, site, "contact.html")
    kinds = {e.label: e.kind for e in obs.elements}
    assert kinds["Full name"] == "text" and kinds["Email address"] == "email"
    assert kinds["Topic"] == "select" and kinds["Message"] == "textarea"
    assert kinds["I agree to be contacted"] == "checkbox"  # visually hidden input, found through its label
    assert by_label(obs, "Topic").options[:3] == ["Choose a topic", "Support", "Sales"]
    send = by_label(obs, "Send message")
    assert send.submits_form and send.form_kind == "generic"
    assert obs.screenshot[:2] == b"\xff\xd8" and len(obs.screenshot) > 5000
    assert await tb.page.evaluate("() => !document.getElementById('__kk_marks__')")  # marks removed after capture


async def test_login_form_flags_password_and_hides_it(browser, site):
    tb, obs = await open_page(browser, site, "login.html")
    pw = by_label(obs, "Password")
    assert pw.is_password and pw.kind == "password" and pw.value == ""
    assert "(secret field)" in pw.line()
    assert by_label(obs, "Sign in").form_kind == "login"


async def test_search_and_payment_forms_are_classified(browser, site):
    _, obs = await open_page(browser, site, "search.html")
    assert by_label(obs, "Search").form_kind == "search"
    _, obs = await open_page(browser, site, "checkout.html")
    assert by_label(obs, "Card number").is_payment and by_label(obs, "CVV").is_payment
    assert by_label(obs, "Pay now").form_kind == "payment"


async def test_hidden_instructions_on_a_page_are_removed_and_flagged(browser, site):
    _, obs = await open_page(browser, site, "shop.html")
    assert obs.injection, "injection attempt should be detected"
    assert "evil.test" not in obs.text and "[removed" in obs.text
    assert "$24.00" in obs.text  # real content stays


async def test_elements_covered_by_a_banner_are_not_offered(browser, site):
    tb, obs = await open_page(browser, site, "cookie.html")
    labels = [e.label for e in obs.elements]
    assert "Accept all" in labels and "Read more" not in labels  # the covered button must not be listed
    result = await run(tb, obs, "click", "Accept all")
    assert result.ok
    obs2 = await observe(tb.page)
    assert "Read more" in [e.label for e in obs2.elements]


async def test_long_page_lists_only_what_is_on_screen_and_counts_the_rest(browser, site):
    tb, obs = await open_page(browser, site, "long.html")
    assert "Bottom button" not in [e.label for e in obs.elements] and obs.below >= 1
    assert "secret price" not in obs.text
    assert (await run(tb, obs, "scroll", value="down")).ok
    await run(tb, obs, "scroll", value="down")
    obs2 = await observe(tb.page)
    assert "secret price" in obs2.text and "Bottom button" in [e.label for e in obs2.elements]


# ---- execution with read-back --------------------------------------------------
async def test_fill_form_and_submit_end_to_end(browser, site):
    tb, obs = await open_page(browser, site, "contact.html")
    assert (await run(tb, obs, "type", "Full name", "Asha Rao")).ok
    assert (await run(tb, obs, "type", "Email address", "asha@example.com")).ok
    assert (await run(tb, obs, "select", "Topic", "Support")).ok
    assert (await run(tb, obs, "click", "I agree")).detail.endswith("(now checked)")
    assert (await run(tb, obs, "click", "Send message")).ok
    text = await tb.page.inner_text("#result")
    assert text == "Thanks Asha Rao, we received your message about Support (asha@example.com)"


async def test_typing_into_a_field_that_refuses_the_value_is_reported_as_failure(browser, site):
    tb, obs = await open_page(browser, site, "contact.html")
    await tb.page.evaluate("() => { const e = document.getElementById('name'); e.addEventListener('input', () => { e.value = ''; }); }")
    result = await run(tb, obs, "type", "Full name", "Asha")
    assert not result.ok and "now reads" in result.detail


async def test_stale_element_number_is_reported_not_misapplied(browser, site):
    tb, obs = await open_page(browser, site, "contact.html")
    await tb.page.evaluate("() => document.querySelectorAll('[data-kk]').forEach(e => e.removeAttribute('data-kk'))")
    result = await run(tb, obs, "click", "Send message")
    assert not result.ok and "no longer on the page" in result.detail


async def test_select_with_unknown_option_lists_choices(browser, site):
    tb, obs = await open_page(browser, site, "contact.html")
    result = await run(tb, obs, "select", "Topic", "Astrology")
    assert not result.ok and "Support" in result.detail


async def test_scroll_at_the_edge_reports_no_movement(browser, site):
    tb, obs = await open_page(browser, site, "contact.html")
    result = await run(tb, obs, "scroll", value="up")
    assert not result.ok and "top" in result.detail


async def test_search_page_returns_results_and_answer_can_be_read(browser, site):
    tb, obs = await open_page(browser, site, "search.html")
    await run(tb, obs, "type", "Search books", "dune")
    await run(tb, obs, "click", "Search")
    obs2 = await observe(tb.page)
    assert "Dune by Frank Herbert" in obs2.text and "$12.99" in obs2.text
    result = await run(tb, obs2, "extract")
    assert result.ok and "$12.99" in (result.answer or "")


async def test_new_tab_is_followed_and_dialogs_never_freeze_the_page(browser, site):
    tb, obs = await open_page(browser, site, "popup.html")
    await run(tb, obs, "click", "Save draft")  # alert()
    assert any("Saved!" in n and "accepted" in n for n in tb.take_notes())
    await run(tb, obs, "click", "Ask me")  # confirm(): must be dismissed, not answered yes
    assert (await tb.page.inner_text("#c")) == "no"
    assert any("dismissed" in n for n in tb.take_notes())
    await run(tb, obs, "click", "Open contact form")
    assert await tb.adopt_new_page()
    assert tb.page.url.endswith("contact.html")
    assert (await observe(tb.page)).title == "Contact us"


async def test_file_downloads_are_blocked_and_reported(browser, site):
    tb, obs = await open_page(browser, site, "popup.html")
    await run(tb, obs, "click", "Download report")
    await tb.page.wait_for_timeout(500)
    assert any("download" in n.lower() and "blocked" in n.lower() for n in tb.take_notes())


async def test_navigate_normalizes_addresses_and_reports_http_errors(browser, site):
    tb, obs = await open_page(browser, site, "index.html")
    ok = await executor.execute(tb.page, AgentAction(action="navigate", value=f"{site}/contact.html"), None)
    assert ok.ok and ok.url_after.endswith("contact.html")
    missing = await executor.execute(tb.page, AgentAction(action="navigate", value=f"{site}/nope.html"), None)
    assert not missing.ok and "404" in missing.detail
    bad = await executor.execute(tb.page, AgentAction(action="navigate", value="http://no-such-host.invalid/"), None)
    assert not bad.ok and "could not be found" in bad.detail


def test_address_parsing_never_mistakes_a_scheme_for_a_website():
    assert parse_target("example.com/a").scheme == "https"
    assert parse_target("localhost:3000").hostname == "localhost"
    assert parse_target("javascript:alert(1)").scheme == "javascript"
    assert parse_target("data:text/html,x").scheme == "data"
    assert parse_target("file:///etc/passwd").scheme == "file"
    assert parse_target("http://a.com").scheme == "http"
