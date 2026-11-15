"""DEMO ONLY: a realistic web form for the Toolstone form filler to fill on the user's computer.

GET /demo/forms/permit (route in api/routes_runner.py): a residential parking permit application.
It is our own static page: nothing is sent or stored. Submitting only shows "Application received
(demo, nothing was sent)" on the page (no network request; the CSP also blocks any form post).
Fields carry standard `autocomplete` tokens so the helper app can match them to the saved profile.
"""
from __future__ import annotations

import base64
import hashlib
import html

from fastapi.responses import HTMLResponse

US_STATES = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"), ("CA", "California"),
    ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"), ("DC", "District of Columbia"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"), ("IL", "Illinois"),
    ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"),
    ("ME", "Maine"), ("MD", "Maryland"), ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"),
    ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"), ("OR", "Oregon"),
    ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"), ("SD", "South Dakota"),
    ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"),
    ("WA", "Washington"), ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"),
]

# (id/name, label, input type, autocomplete token or "", required, extra attributes)
APPLICANT = [
    ("full_name", "Full name", "text", "name", True, ""),
    ("email", "Email", "email", "email", True, ""),
    ("phone", "Phone", "tel", "tel", False, ""),
]
ADDRESS = [
    ("street_address", "Street address", "text", "street-address", True, ""),
    ("city", "City", "text", "address-level2", True, ""),
]
VEHICLE = [
    ("license_plate", "License plate", "text", "", True, ' spellcheck="false" autocapitalize="characters"'),
    ("vehicle_make", "Vehicle make", "text", "", False, ""),
    ("vehicle_model", "Vehicle model", "text", "", False, ""),
    ("vehicle_color", "Vehicle color", "text", "", False, ""),
]

STYLE = """
:root { --ink: #1b1f24; --muted: #59636e; --line: #d0d7de; --brand: #0b3d91; --brand-ink: #fff;
        --bg: #f5f7fa; --card: #fff; --ok: #116329; --ok-bg: #dafbe1; --warn-bg: #fff8c5; --warn: #6b4b00; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
header { background: var(--brand); color: var(--brand-ink); }
.bar { max-width: 760px; margin: 0 auto; padding: 14px 16px; display: flex; align-items: baseline; gap: 12px; }
.city { font-weight: 700; letter-spacing: 0.02em; }
.dept { opacity: 0.85; font-size: 14px; }
.demo { background: var(--warn-bg); color: var(--warn); border-bottom: 1px solid #eac54f; font-size: 14px; }
.demo p { max-width: 760px; margin: 0 auto; padding: 8px 16px; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 28px; line-height: 1.2; margin: 0 0 6px; }
.lede { color: var(--muted); margin: 0 0 20px; }
form, .done { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 8px 20px 20px; }
fieldset { border: 0; padding: 0; margin: 16px 0 0; }
legend { font-weight: 700; font-size: 18px; padding: 0; margin-bottom: 4px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
.full { grid-column: 1 / -1; }
.field { display: flex; flex-direction: column; gap: 4px; }
label { font-weight: 600; font-size: 15px; }
.req { color: #cf222e; margin-left: 2px; }
input[type=text], input[type=email], input[type=tel], select {
  font: inherit; color: inherit; background: #fff; border: 1px solid #8c959f; border-radius: 6px;
  padding: 9px 10px; min-height: 42px; width: 100%; }
input:focus, select:focus, button:focus { outline: 3px solid #54aeff; outline-offset: 1px; }
.check { display: flex; gap: 10px; align-items: flex-start; margin-top: 18px; font-weight: 600; }
.check input { width: 20px; height: 20px; margin-top: 2px; }
.actions { margin-top: 18px; display: flex; gap: 12px; align-items: center; }
button { font: inherit; font-weight: 700; background: var(--brand); color: var(--brand-ink); border: 0;
         border-radius: 6px; padding: 11px 22px; min-height: 44px; cursor: pointer; }
.hint { color: var(--muted); font-size: 14px; }
.done { padding: 20px; border-color: #4ac26b; background: var(--ok-bg); color: var(--ok); }
.done h2 { margin: 0 0 6px; font-size: 22px; }
.done p { margin: 0; color: var(--ink); }
footer { color: var(--muted); font-size: 13px; margin-top: 24px; }
@media (max-width: 560px) { .grid { grid-template-columns: 1fr; } h1 { font-size: 24px; } }
"""

SCRIPT = """
(function () {
  var form = document.getElementById("permit-form");
  var done = document.getElementById("done");
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    form.hidden = true;
    done.hidden = false;
    done.focus();
  });
})();
"""


def _csp_hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


HEADERS = {
    # Only this page's own inline style and script (by hash). No form posts, no network at all.
    "Content-Security-Policy": f"default-src 'none'; style-src {_csp_hash(STYLE)}; script-src {_csp_hash(SCRIPT)}; "
                               "img-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'; "
                               "frame-ancestors 'none'",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "public, max-age=300",
}


def _field(fid: str, label: str, kind: str, auto: str, required: bool, extra: str, wide: bool = False) -> str:
    e = html.escape
    star = '<span class="req" aria-hidden="true">*</span>' if required else ""
    attrs = f' autocomplete="{e(auto)}"' if auto else ""
    attrs += " required" if required else ""
    return (f'<div class="field{" full" if wide else ""}"><label for="{e(fid)}">{e(label)}{star}</label>'
            f'<input type="{e(kind)}" id="{e(fid)}" name="{e(fid)}"{attrs}{extra}></div>')


def permit_html() -> str:
    applicant = "".join(_field(*f, wide=(f[0] == "full_name")) for f in APPLICANT)
    address = "".join(_field(*f, wide=(f[0] == "street_address")) for f in ADDRESS)
    states = "".join(f'<option value="{code}">{html.escape(name)}</option>' for code, name in US_STATES)
    vehicle = "".join(_field(*f) for f in VEHICLE)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Residential Parking Permit Application · City of Atlanta (demo)</title>
<style>{STYLE}</style></head>
<body>
<header><div class="bar"><span class="city">City of Atlanta</span><span class="dept">Department of Transportation · Parking</span></div></header>
<div class="demo"><p>Demo page for the Toolstone form filler. Not affiliated with the City of Atlanta. Nothing you enter is sent or stored.</p></div>
<main>
<h1>Residential Parking Permit Application</h1>
<p class="lede">Apply for a permit to park on your residential street. Fields marked <span class="req">*</span> are required.</p>
<form id="permit-form" method="post" aria-label="Residential Parking Permit Application">
<fieldset><legend>Applicant</legend><div class="grid">{applicant}</div></fieldset>
<fieldset><legend>Home address</legend><div class="grid">{address}
<div class="field"><label for="state">State<span class="req" aria-hidden="true">*</span></label>
<select id="state" name="state" autocomplete="address-level1" required><option value="">Select a state</option>{states}</select></div>
<div class="field"><label for="zip">ZIP<span class="req" aria-hidden="true">*</span></label>
<input type="text" id="zip" name="zip" autocomplete="postal-code" inputmode="numeric" maxlength="10" required></div>
</div></fieldset>
<fieldset><legend>Vehicle</legend><div class="grid">{vehicle}</div></fieldset>
<fieldset><legend>Permit</legend><div class="grid">
<div class="field"><label for="permit_type">Permit type<span class="req" aria-hidden="true">*</span></label>
<select id="permit_type" name="permit_type" required><option value="residential" selected>Residential</option><option value="visitor">Visitor</option></select></div>
</div></fieldset>
<label class="check" for="certify"><input type="checkbox" id="certify" name="certify" required> I certify this information is correct</label>
<div class="actions"><button type="submit" id="submit">Submit</button><span class="hint">Takes about a minute.</span></div>
</form>
<section id="done" class="done" role="status" aria-live="polite" tabindex="-1" hidden>
<h2>Application received (demo, nothing was sent)</h2>
<p>This is a demo form. No application was filed and nothing you typed left this page.</p>
</section>
<footer>Demo form served by Toolstone for testing the form filler.</footer>
</main>
<script>{SCRIPT}</script>
</body></html>"""


PERMIT_HTML = permit_html()


def permit_page() -> HTMLResponse:
    return HTMLResponse(PERMIT_HTML, headers=HEADERS)
