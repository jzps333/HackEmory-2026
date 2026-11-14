"""Click past harmless barriers, and robot checks / sign-in walls as evidence.

Offline: the label rules, the robot-check and sign-in detectors (on the facts the page JS
returns), and the verdict bump in api/scan.py. The last few tests run the real page JS on small
HTML snippets in a local Chromium; they skip when Playwright isn't installed (as in the main
venv). No network: every request from those pages is aborted.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox"))
import run_scan as rs  # noqa: E402  (Playwright is only imported inside scan())

from api import config, jev  # noqa: E402
from api import scan as api_scan  # noqa: E402
from api.schema import JevChecks  # noqa: E402


# ---------- label rules ----------

@pytest.mark.parametrize("label,cls", [
    ("Reject all", "reject"), ("REJECT ALL", "reject"), ("Decline", "reject"),
    ("Necessary only", "reject"), ("Only necessary cookies", "reject"),
    ("Continue without accepting", "reject"), ("Tout refuser", "reject"), ("Rechazar todo", "reject"),
    ("Accept", "accept"), ("Accept all cookies", "accept"), ("I agree", "accept"),
    ("OK", "accept"), ("Aceptar", "accept"), ("J’accepte", "accept"),
    ("Continue", "continue"), ("Continue >", "continue"), ("Continue to site", "continue"),
    ("Proceed", "continue"), ("Skip", "continue"), ("Skip Ad", "continue"), ("Continuar", "continue"),
    ("Close", "close"), ("×", "close"), ("✕", "close"), ("Close ×", "close"), ("Close dialog", "close"),
    ("No thanks", "close"), ("No, thanks!", "close"), ("Not now", "close"), ("Got it!", "close"),
    ("Dismiss", "close"), ("Fermer", "close"), ("Cerrar", "close"),
    ("Dismiss sign-in info.", "close"), ("Close subscribe banner", "close"),   # closing a pop-up
    ("I am 18 or older", "age"), ("I'm 21+", "age"), ("I’m over 18", "age"),
    ("Yes, I am 18 or older", "age"), ("Enter", "enter"), ("Yes", "enter"),
    ("Click here if you are not redirected", "redirect"), ("click here", "here"),
])
def test_allowed_labels(label, cls):
    assert rs.classify_label(label) == cls


@pytest.mark.parametrize("label", [
    "Sign in", "Log in", "Login", "Sign up", "Register", "Create account", "Subscribe",
    "Subscribe now", "Pay now", "Pay $4.99", "Buy now", "Checkout", "Place order", "Donate",
    "Add card", "Download", "Download now", "Install", "Install app", "Get the app",
    "Open in app", "Allow notifications", "Enable notifications", "Turn on notifications",
    "Submit", "Send", "Call now", "Call us", "Text me", "Verify", "I'm not a robot",
    "Verify you are human", "Claim your prize", "Redeem", "Unlock", "Start free trial",
    "Continue with Google", "Continue with Apple", "Accept and subscribe", "Continue to payment",
    "Iniciar sesión", "Descargar", "Pagar", "Se connecter", "Télécharger",
    "Close account", "Close and sign in", "Dismiss to continue to payment", "Hide password",
    "Skip to main content",          # an accessibility link, not a barrier
    "Read more", "Menu", "", "   ", "x" * 90,
])
def test_forbidden_or_unknown_labels(label):
    assert rs.classify_label(label) is None


def cand(label, **kw):
    base = {"label": label, "tag": "button", "type": "button", "href": "", "abs_href": "",
            "download": False, "overlay": True, "top": 600, "submits_fillable_form": False,
            "fillable_ctx": False, "ctx_text": "", "ctx_attrs": ""}
    base.update(kw)
    return base


COOKIE_CTX = "We use cookies to improve your experience. Reject all Accept all"


def test_cookie_buttons_need_consent_context():
    assert rs.click_kind(cand("Accept all", ctx_text=COOKIE_CTX)) == ("cookie", "accept")
    assert rs.click_kind(cand("Reject all", ctx_text=COOKIE_CTX)) == ("cookie", "reject")
    assert rs.click_kind(cand("Accept", ctx_attrs="onetrust-banner-sdk")) == ("cookie", "accept")
    assert rs.click_kind(cand("Accept all cookies")) == ("cookie", "accept")   # says so itself
    # "Accept"/"I agree" with nothing about cookies around it: terms, offers... not ours.
    assert rs.click_kind(cand("I agree", ctx_text="Agree to our terms to claim your reward")) is None
    assert rs.click_kind(cand("I agree", overlay=False,
                              ctx_text="By joining you agree to our privacy policy")) is None
    # "Decline" on some other pop-up is just a dismissal.
    assert rs.click_kind(cand("Decline", ctx_text="Get 10% off today!")) == ("close", None)


def test_reject_is_preferred_over_accept():
    cands = [cand("Accept all", ctx_text=COOKIE_CTX), cand("×", ctx_text=COOKIE_CTX),
             cand("Reject all", ctx_text=COOKIE_CTX)]
    assert rs.choose_click(cands) == (2, "cookie", "reject")
    assert rs.choose_click(cands[:2]) == (1, "cookie", "dismiss")   # close it without agreeing
    assert rs.choose_click(cands[:1]) == (0, "cookie", "accept")


def test_priority_cookie_then_age_then_close_then_continue():
    cands = [cand("Continue", overlay=False), cand("Close"), cand("I am 18 or older"),
             cand("Got it", ctx_text=COOKIE_CTX + " Got it")]
    assert rs.choose_click(cands) == (3, "cookie", "dismiss")   # "Got it" on a cookie notice
    cands = [cand("Continue", overlay=False), cand("Close"), cand("I am 18 or older")]
    assert rs.choose_click(cands) == (2, "age_gate", None)
    assert rs.choose_click(cands[:2]) == (1, "close", None)
    assert rs.choose_click(cands[:1]) == (0, "continue", None)
    assert rs.choose_click([]) is None


def test_already_clicked_labels_are_skipped():
    cands = [cand("Close"), cand("Continue", overlay=False)]
    assert rs.choose_click(cands, skip_labels={"close"}) == (1, "continue", None)


def test_close_needs_an_overlay():
    assert rs.click_kind(cand("×", overlay=False)) is None
    assert rs.click_kind(cand("×", overlay=True)) == ("close", None)


def test_never_submits_a_form_with_fields():
    assert rs.click_kind(cand("Continue", type="submit", submits_fillable_form=True)) is None
    assert rs.click_kind(cand("Continue", fillable_ctx=True)) is None     # next to an email box
    assert rs.click_kind(cand("Close", submits_fillable_form=True)) is None


def test_login_wall_allows_only_cookie_and_close():
    cands = [cand("Continue", overlay=False), cand("Reject all", ctx_text=COOKIE_CTX)]
    assert rs.choose_click(cands, login_wall=True) == (1, "cookie", "reject")
    assert rs.choose_click(cands[:1], login_wall=True) is None


def test_file_links_and_odd_schemes_are_never_clicked():
    for href in ("https://x.test/app.apk", "https://x.test/Setup.EXE", "/files/invoice.pdf",
                 "https://x.test/update.dmg?x=1"):
        assert rs.click_kind(cand("Continue", tag="a", href=href, abs_href=href)) is None
    assert rs.click_kind(cand("Continue", tag="a", href="/x", abs_href="https://x.test/x",
                              download=True)) is None
    for href in ("tel:+15551234", "sms:+15551234", "mailto:a@b.test", "intent://scan#Intent;end",
                 "market://details?id=x", "data:text/html,hi"):
        assert rs.click_kind(cand("Continue", tag="a", href=href, abs_href=href)) is None
    assert rs.click_kind(cand("Continue", tag="a", href="/next",
                              abs_href="https://x.test/next")) == ("continue", None)


def test_age_gate_enter_needs_age_context():
    assert rs.click_kind(cand("Enter", ctx_text="You must be 21 or older to enter this site")) \
        == ("age_gate", None)
    assert rs.click_kind(cand("Enter", ctx_text="Enter the draw")) is None
    assert rs.click_kind(cand("Yes", ctx_text="Are you sure you want to pay?")) is None


def test_redirect_links():
    link = dict(tag="a", href="https://real.test/", abs_href="https://real.test/", overlay=False)
    assert rs.click_kind(cand("Click here if you are not redirected", **link)) == ("redirect_link", None)
    assert rs.click_kind(cand("click here", ctx_text="You will be redirected automatically. "
                                                     "If not, click here", **link)) == ("redirect_link", None)
    assert rs.click_kind(cand("click here", ctx_text="To win a prize click here", **link)) is None
    assert rs.click_kind(cand("click here if not redirected", tag="button")) is None   # links only
    assert rs.click_kind(cand("Click here if you are not redirected", tag="a", href="#",
                              abs_href="https://x.test/#")) is None


def test_clip_label():
    assert rs.clip_label("  Reject \n all ") == "Reject all"
    assert len(rs.clip_label("a" * 200)) == 60


def test_same_site():
    assert rs.same_site("www.bbc.co.uk", "news.bbc.co.uk")
    assert rs.same_site("consent.example.com", "www.example.com")
    assert not rs.same_site("cdn.privacy-mgmt.com", "www.example.com")
    assert not rs.same_site("evil.co.uk", "bbc.co.uk")
    assert not rs.same_site("", "example.com")


# ---------- robot checks and sign-in walls ----------

def state(**kw):
    base = {"iframes": [], "markers": [], "password_visible": 0, "user_field_visible": False,
            "signin_text": "", "text": "", "text_len": 0, "title": ""}
    base.update(kw)
    return base


def frame(src, visible=True):
    return {"src": src, "visible": visible, "top": 300, "w": 304, "h": 78}


RECAPTCHA = "https://www.google.com/recaptcha/api2/anchor?ar=1&k=6Le-x&co=aHR0&hl=en&size=normal"


@pytest.mark.parametrize("src,kind", [
    (RECAPTCHA, "recaptcha"),
    ("https://www.recaptcha.net/recaptcha/api2/bframe?hl=en&k=x", "recaptcha"),
    ("https://www.google.com/recaptcha/enterprise/anchor?k=x&size=compact", "recaptcha"),
    ("https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=checkbox&id=1", "hcaptcha"),
    ("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/x",
     "turnstile"),
    ("https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible", None),   # v3 badge
    ("https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html#frame=checkbox-invisible", None),
    ("https://www.youtube.com/embed/xyz", None),
    ("https://evil.test/recaptcha/anchor", None),
])
def test_captcha_frame_kind(src, kind):
    assert rs.captcha_frame_kind(src) == kind


def test_visible_captcha_on_short_page_is_detected():
    s = state(iframes=[frame(RECAPTCHA)], text="reCAPTCHA demo Submit", text_len=40)
    assert rs.detect_bot_check(s) == {"detected": True, "kind": "recaptcha"}


def test_hidden_or_invisible_captcha_is_not_detected():
    assert not rs.detect_bot_check(state(iframes=[frame(RECAPTCHA, visible=False)], text_len=40))["detected"]
    v3 = "https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible"
    assert not rs.detect_bot_check(state(iframes=[frame(v3)], text_len=40))["detected"]


def test_captcha_at_the_end_of_a_long_page_does_not_gate_it():
    s = state(iframes=[frame(RECAPTCHA)], text="news " * 2000, text_len=10000)
    assert rs.detect_bot_check(s) == {"detected": False, "kind": None}


def test_cloudflare_challenge_page():
    assert rs.detect_bot_check(state(markers=["cf_chl_opt"], text_len=9000))["kind"] == "turnstile"
    s = state(title="Just a moment...", text="Verifying you are human. This may take a few seconds.",
              text_len=60)
    assert rs.detect_bot_check(s) == {"detected": True, "kind": "text"}


@pytest.mark.parametrize("text", [
    "Verify you are human by completing the action below.",
    "Checking your browser before accessing example.test",
    "Please confirm that you are a human. Press & Hold",
    "I'm not a robot",
    "Performing security verification. This website verifies you are not a bot.",
])
def test_robot_check_wording_on_a_short_page(text):
    assert rs.detect_bot_check(state(text=text, text_len=len(text)))["kind"] == "text"


def test_robot_check_wording_in_a_long_article_is_not_a_gate():
    text = "How CAPTCHAs work: sites ask you to verify you are human. " + "More text. " * 400
    assert not rs.detect_bot_check(state(text=text[:2000], text_len=len(text)))["detected"]


def test_detectors_tolerate_missing_state():
    assert rs.detect_bot_check(None) == {"detected": False, "kind": None}
    assert rs.detect_login_wall(None) is False


def test_login_wall():
    assert rs.detect_login_wall(state(password_visible=1, text_len=9000))
    assert rs.detect_login_wall(state(user_field_visible=True, signin_text="Sign in | Next",
                                      text_len=300))          # email-first sign-in
    assert not rs.detect_login_wall(state(user_field_visible=True, signin_text="Newsletter",
                                          text_len=300))
    assert not rs.detect_login_wall(state(user_field_visible=True, signin_text="Log in",
                                          text_len=8000))     # a long page with a login link


# ---------- evidence in api/scan.py and Jev ----------

def test_bot_check_makes_safe_suspicious():
    verdict, score, scam_type = api_scan.decide(JevChecks(malicious_p=0.1), bot_check=True)
    assert verdict == "suspicious" and score >= config.SECOND_LOOK_SCORE and scam_type == "other"
    assert api_scan.decide(JevChecks(malicious_p=0.1))[0] == "safe"
    # Never softens a worse verdict.
    assert api_scan.decide(JevChecks(malicious_p=0.95), bot_check=True)[0] == "malicious"


def test_sandbox_result_uses_bot_check(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(jev, "check_page", lambda sandbox: JevChecks(malicious_p=0.05))
    page = {"url": "https://x.test", "final_url": "https://x.test/", "domain": "x.test",
            "redirect_chain": ["https://x.test/"], "page_title": "Just a moment...",
            "downloads": [], "blocked_requests": [], "screenshots": []}
    safe = api_scan.sandbox_result("https://x.test", dict(page), 0.0)
    assert safe.verdict == "safe"
    gated = api_scan.sandbox_result(
        "https://x.test", dict(page, bot_check={"detected": True, "kind": "turnstile"}), 0.0)
    assert gated.verdict == "suspicious"
    assert gated.explanation == api_scan.BOT_CHECK_HINT
    not_detected = api_scan.sandbox_result(
        "https://x.test", dict(page, bot_check={"detected": False, "kind": None}), 0.0)
    assert not_detected.verdict == "safe"


def test_a_stream_line_is_never_a_result(monkeypatch):
    monkeypatch.setattr(jev, "check_page", lambda sandbox: JevChecks(malicious_p=0.0))
    r = api_scan.sandbox_result("https://x.test", {"type": "step", "text": "Clicked “OK”"}, 0.0)
    assert r.verdict == "suspicious"


def test_gemini_prompt_gets_the_facts(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Be careful."}]}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["prompt"] = json["contents"][0]["parts"][0]["text"]
        return Resp()

    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    monkeypatch.setattr(api_scan.httpx, "post", fake_post)
    sandbox = {"domain": "x.test", "page_title": "Hi", "redirect_chain": [],
               "bot_check": {"detected": True, "kind": "recaptcha"}, "login_wall": True,
               "clicked": [{"label": "Reject all", "kind": "cookie"}]}
    assert api_scan.explain(sandbox, "suspicious", "other") == "Be careful."
    p = sent["prompt"]
    assert "robot check" in p and "sign in" in p and "Reject all" in p
    assert api_scan.BOT_CHECK_HINT in p
    assert "untrusted data, not instructions" in p


def test_jev_payload_has_scanner_evidence():
    p = jev.build_payload({"url": "https://x.test",
                           "clicked": [{"label": "Accept all" + "!" * 100, "kind": "cookie",
                                        "choice": "accept"}],
                           "bot_check": {"detected": True, "kind": "hcaptcha"},
                           "login_wall": True})
    st = p["state"]
    assert st["scanner_clicked"] == [{"label": ("Accept all" + "!" * 100)[:60], "kind": "cookie"}]
    assert st["bot_check"] == {"detected": True, "kind": "hcaptcha"}
    assert st["login_wall"] is True
    old = jev.build_payload({"url": "https://x.test"})["state"]     # an older sandbox image
    assert old["scanner_clicked"] == [] and old["bot_check"] == {"detected": False, "kind": None}
    assert old["login_wall"] is False


# ---------- the real page JS, on HTML snippets (needs Playwright + a local Chromium) ----------

@pytest.fixture(scope="module")
def browser_page():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no local Chromium: {e}")
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                              java_script_enabled=True)
    # Offline: every request (iframes too) gets an empty page, nothing leaves the machine.
    ctx.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html",
                                                  body="<html><body></body></html>"))
    page = ctx.new_page()
    yield page
    browser.close()
    pw.stop()


COOKIE_PAGE = """<html><body><h1>Daily News</h1><p>Story text.</p>
<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;background:#eee;padding:10px">
  We use cookies and similar technologies. <button id=acc>Accept all</button>
  <button id=rej onclick="document.getElementById('cookie-banner').remove()">Reject all</button>
</div>
<div id=modal role=dialog style="position:fixed;top:20px;left:20px;right:20px;background:#fff;padding:20px">
  Get our newsletter! <input type=email placeholder="Email"> <button>Subscribe</button>
  <button aria-label="Close" onclick="this.parentElement.remove()">×</button>
</div></body></html>"""


def test_js_clicks_reject_then_closes_modal(browser_page):
    browser_page.set_content(COOKIE_PAGE)
    clicked = rs.click_past(browser_page, False, {"on": False, "urls": []})
    assert clicked == [{"label": "Reject all", "kind": "cookie", "choice": "reject"},
                       {"label": "Close", "kind": "close"}]
    assert browser_page.evaluate("!document.getElementById('cookie-banner') && !document.getElementById('modal')")
    assert browser_page.evaluate("document.querySelector('input') === null")


def test_js_never_presses_continue_on_a_sign_in_form(browser_page):
    browser_page.set_content("""<html><head><title>Sign in</title></head><body><h1>Sign in</h1>
      <form action="/next"><input type=email name=email><button>Continue</button></form>
      <a href="/forgot">Forgot?</a></body></html>""")
    st = rs.page_state(browser_page)
    assert rs.detect_login_wall(st)
    assert rs.click_past(browser_page, False, {"on": False, "urls": []}) == []


def test_js_password_page_is_a_login_wall(browser_page):
    browser_page.set_content("""<html><body><form><input name=login><input type=password name=pw>
      <input type=submit value="Sign in"></form></body></html>""")
    assert rs.detect_login_wall(rs.page_state(browser_page))


def test_js_recaptcha_gate_is_detected_and_left_alone(browser_page):
    browser_page.set_content(f"""<html><body><form><div class=g-recaptcha>
      <iframe src="{RECAPTCHA}" width=304 height=78 title="reCAPTCHA"></iframe></div>
      <button type=button onclick="document.title='clicked'">Continue</button></form></body></html>""")
    st = rs.page_state(browser_page)
    assert rs.detect_bot_check(st) == {"detected": True, "kind": "recaptcha"}
    assert rs.click_past(browser_page, False, {"on": False, "urls": []}) == []
    assert browser_page.title() != "clicked"


def test_js_v3_badge_is_not_a_robot_check(browser_page):
    browser_page.set_content("""<html><body><p>Menu: soup, salad.</p><div style="position:fixed;bottom:14px;right:0">
      <iframe src="https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible" width=256 height=60></iframe>
      </div></body></html>""")
    assert rs.detect_bot_check(rs.page_state(browser_page))["detected"] is False


def test_js_age_gate_and_file_link(browser_page):
    browser_page.set_content("""<html><body>
      <div style="position:fixed;inset:0;background:#000;color:#fff" id=gate>
        You must be 21 or older to enter. <a href="/app.apk">Continue</a>
        <button onclick="document.getElementById('gate').remove()">Enter</button></div></body></html>""")
    clicked = rs.click_past(browser_page, False, {"on": False, "urls": []})
    assert clicked == [{"label": "Enter", "kind": "age_gate"}]


def test_js_turnstile_inside_a_shadow_root_is_found(browser_page):
    browser_page.set_content("""<html><body><h1>Dummy Login</h1><div id=host></div><script>
      const root = document.getElementById('host').attachShadow({mode: 'closed'});
      const f = document.createElement('iframe');
      f.src = 'https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/x/normal';
      f.width = 300; f.height = 65; root.appendChild(f);
    </script></body></html>""")
    browser_page.wait_for_timeout(300)
    st = rs.page_state(browser_page)
    assert rs.detect_bot_check(st) == {"detected": True, "kind": "turnstile"}
