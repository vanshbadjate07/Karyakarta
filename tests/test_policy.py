from karyakarta.models import AgentAction, Element
from karyakarta.safety.policy import Decision, PolicyContext, classify_form, evaluate


def el(**kw) -> Element:
    base = dict(ref=1, tag="input", kind="text", label="Field")
    base.update(kw)
    return Element(**base)


def act(name, mark=1, value=None) -> AgentAction:
    return AgentAction(action=name, mark=mark, value=value)


def verdict(action, element=None, url="https://shop.example/page", **ctx):
    return evaluate(action, element, url, PolicyContext(**ctx))


# ---- credentials never reach the model ------------------------------------
def test_password_field_requires_user_entry():
    v = verdict(act("type", value="hunter2"), el(kind="password", label="Password", is_password=True))
    assert v.decision == Decision.CREDENTIAL
    assert "enter it yourself" in v.reasons[0]


def test_otp_and_card_fields_require_user_entry():
    assert verdict(act("type", value="123456"), el(label="OTP", is_otp=True)).decision == Decision.CREDENTIAL
    assert verdict(act("type", value="4111"), el(label="Card number", is_payment=True)).decision == Decision.CREDENTIAL


def test_model_supplied_value_cannot_downgrade_a_secret_field():
    v = verdict(act("type", value="my-real-password"), el(is_password=True, kind="password"))
    assert v.decision == Decision.CREDENTIAL


def test_plain_text_field_is_allowed():
    assert verdict(act("type", value="Asha"), el(label="Full name")).decision == Decision.ALLOW


# ---- final submits ----------------------------------------------------------
def test_submit_button_in_generic_form_asks_even_if_labelled_next():
    button = el(kind="button", tag="button", label="Next", submits_form=True, form_kind="generic", form_id="f0")
    v = verdict(act("click"), button)
    assert v.decision == Decision.ASK and v.category == "submit"


def test_search_form_submit_is_allowed():
    button = el(kind="button", label="Search", submits_form=True, form_kind="search", form_id="f0")
    assert verdict(act("click"), button).decision == Decision.ALLOW


def test_login_submit_asks_until_user_supplied_credentials():
    button = el(kind="button", label="Sign in", submits_form=True, form_kind="login", form_id="f0")
    assert verdict(act("click"), button).decision == Decision.ASK
    assert verdict(act("click"), button, credentials_given_forms={"f0"}).decision == Decision.ALLOW


def test_payment_form_submit_always_asks_even_after_credentials():
    button = el(kind="button", label="Continue", submits_form=True, form_kind="payment", form_id="f2")
    assert verdict(act("click"), button, credentials_given_forms={"f2"}).decision == Decision.ASK


def test_approved_form_does_not_ask_twice():
    button = el(kind="button", label="Send", submits_form=True, form_kind="generic", form_id="f1")
    assert verdict(act("click"), button, approved_forms={"f1"}).decision == Decision.ALLOW


def test_irreversible_button_text_asks_without_a_form():
    for text in ("Place order", "Delete account", "Pay now", "Confirm booking", "Unsubscribe"):
        v = verdict(act("click"), el(tag="button", kind="button", label=text))
        assert v.decision == Decision.ASK, text


def test_harmless_buttons_are_allowed():
    for text in ("Next page", "Show more", "Filter", "Add to cart", "Close"):
        assert verdict(act("click"), el(tag="button", kind="button", label=text)).decision == Decision.ALLOW, text


def test_pressing_enter_in_a_generic_form_counts_as_submit():
    field = el(kind="text", label="Email", form_id="f1", form_kind="generic")
    assert verdict(act("press", value="Enter"), field).decision == Decision.ASK
    search = el(kind="search", label="Search", form_id="f1", form_kind="search")
    assert verdict(act("press", value="Enter"), search).decision == Decision.ALLOW


# ---- navigation -------------------------------------------------------------
def test_dangerous_schemes_are_denied():
    for url in ("javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi", "chrome://settings"):
        assert verdict(act("navigate", mark=None, value=url)).decision == Decision.DENY, url


def test_own_control_port_is_always_denied():
    v = verdict(act("navigate", mark=None, value="http://127.0.0.1:8765/api/tasks"), own_ports=frozenset({8765}), allow_private_hosts=True)
    assert v.decision == Decision.DENY


def test_private_addresses_ask_unless_allowed():
    assert verdict(act("navigate", mark=None, value="http://192.168.1.10/admin")).decision == Decision.ASK
    assert verdict(act("navigate", mark=None, value="http://localhost:3000")).decision == Decision.ASK
    assert verdict(act("navigate", mark=None, value="http://192.168.1.10/"), allow_private_hosts=True).decision == Decision.ALLOW


def test_public_sites_and_bare_domains_are_allowed():
    assert verdict(act("navigate", mark=None, value="https://example.com/a")).decision == Decision.ALLOW
    assert verdict(act("navigate", mark=None, value="example.com")).decision == Decision.ALLOW


def test_payment_urls_ask():
    assert verdict(act("navigate", mark=None, value="https://shop.example/checkout")).decision == Decision.ASK


# ---- prompt injection hardening ---------------------------------------------
def test_when_injection_suspected_leaving_the_site_and_typing_need_confirmation():
    assert verdict(act("navigate", mark=None, value="https://other.example/"), injection_suspected=True).decision == Decision.ASK
    assert verdict(act("type", value="x"), el(label="Name"), injection_suspected=True).decision == Decision.ASK
    link = el(tag="a", kind="link", label="Offer", href="evil.example/x")
    assert verdict(act("click"), link, injection_suspected=True).decision == Decision.ASK


def test_file_uploads_are_denied():
    assert verdict(act("click"), el(kind="file", label="Upload")).decision == Decision.DENY


# ---- form classification ----------------------------------------------------
def test_form_classification():
    assert classify_form([{"kind": "password"}, {"kind": "email"}]) == "login"
    assert classify_form([{"kind": "password"}, {"kind": "password"}]) == "signup"
    assert classify_form([{"kind": "text", "is_payment": True}]) == "payment"
    assert classify_form([{"kind": "search", "name": "q"}]) == "search"
    assert classify_form([{"kind": "text", "name": "q"}]) == "search"
    assert classify_form([{"kind": "text", "name": "name"}, {"kind": "email", "name": "email"}]) == "generic"
    assert classify_form([]) == ""
