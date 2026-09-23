"""Synthetic evidence and JS DOM fixtures: no browser, network or real account data."""

import json
from pathlib import Path
import subprocess
import sys

import playwright
import pytest

from xhs_sidecar.login_detection import (
    LOGIN_OBSERVATION_SCRIPT, classify_login_evidence, parse_login_observation,
)
from xhs_sidecar.models import LoginEvidence


def evidence(**changes):
    fields = dict(
        current_url_classification="OFFICIAL_PAGE", page_ready=True,
        login_dialog_present=False, login_button_present=False,
        authenticated_account_entry_present=False, authenticated_user_state=None,
        account_identity_available=False, verification_present=False,
        access_restriction_present=False,
    )
    fields.update(changes)
    return LoginEvidence(**fields)


@pytest.mark.parametrize("changes,expected", [
    ({"authenticated_user_state": True}, "AUTHENTICATED"),  # A: obsolete DOM absent; no ID.
    ({}, "UNKNOWN"),  # B/F: absence is not a positive login signal.
    ({"account_identity_available": True}, "UNKNOWN"),
    ({"authenticated_account_entry_present": True}, "UNKNOWN"),
    ({"authenticated_account_entry_present": True, "account_identity_available": True,
      "account_entry_identity_matches": True},
     "AUTHENTICATED"),  # E: corroborated DOM fallback if guest flag disappears.
    ({"authenticated_account_entry_present": True, "account_identity_available": True}, "UNKNOWN"),
    ({"login_button_present": True, "authenticated_user_state": True}, "LOGIN_REQUIRED"),
    ({"login_dialog_present": True, "authenticated_user_state": True}, "LOGIN_REQUIRED"),
    ({"authenticated_user_state": False, "authenticated_account_entry_present": True,
      "account_identity_available": True}, "LOGIN_REQUIRED"),
    ({"verification_present": True, "authenticated_user_state": True,
      "authenticated_account_entry_present": True}, "VERIFICATION_REQUIRED"),
    ({"access_restriction_present": True, "authenticated_user_state": True},
     "VERIFICATION_REQUIRED"),
    ({"current_url_classification": "VERIFICATION", "authenticated_user_state": True},
     "VERIFICATION_REQUIRED"),
    ({"current_url_classification": "LOGIN", "authenticated_user_state": True}, "LOGIN_REQUIRED"),
    ({"current_url_classification": "FOREIGN_ORIGIN", "authenticated_user_state": True}, "UNKNOWN"),
    ({"current_url_classification": "OTHER_OFFICIAL_PAGE", "authenticated_user_state": True},
     "UNKNOWN"),
    ({"page_ready": False, "authenticated_user_state": True}, "UNKNOWN"),
    ({"verification_present": None, "authenticated_user_state": True}, "UNKNOWN"),
    ({"login_button_present": None, "authenticated_user_state": True}, "UNKNOWN"),
])
def test_conservative_classifier(changes, expected):
    assert classify_login_evidence(evidence(**changes)) == expected


def test_all_unknown_is_not_authenticated():
    assert classify_login_evidence(LoginEvidence()) == "UNKNOWN"


@pytest.mark.parametrize("raw", [None, [], {"state": "AUTHENTICATED"}, {
    "evidence": {"current_url_classification": "SECRET_XSEC_T03", "token": "SECRET_COOKIE_T03"}
}, {"evidence": {"login_button_present": "false"}}])
def test_malformed_or_legacy_output_fails_closed_without_content(raw):
    result = parse_login_observation(raw)
    assert result.state == "UNKNOWN"
    assert "SECRET_" not in repr(result)


@pytest.mark.parametrize("account", [None, "", "has spaces", "a" * 129, 123])
def test_no_reliable_identity_does_not_block_explicit_authenticated_state(account):
    result = parse_login_observation({
        "evidence": evidence(authenticated_user_state=True, account_identity_available=True).model_dump(),
        "stable_id": account,
    })
    assert result.state == "AUTHENTICATED"
    assert result.identity.stable_id is None
    assert result.evidence.account_identity_available is False


def test_dom_fallback_cannot_claim_identity_without_a_valid_private_id():
    result = parse_login_observation({"evidence": evidence(
        authenticated_account_entry_present=True, account_identity_available=True
    ).model_dump()})
    assert result.state == "UNKNOWN"


# Execute the actual extraction script, not a fake returning its expected result.
# Node is already shipped by the pinned Playwright package. The VM has only a
# synthetic document/window and no require/process/fetch or browser/network API.
NODE_FIXTURE = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const element = (text, href) => ({textContent:text || '', getClientRects:()=>[1],
  getAttribute:()=>href});
const result = input.fixtures.map(f => {
  const document = {
    readyState:f.readyState || 'complete', title:f.title || '',
    querySelectorAll(selector) {
      if (selector === 'a[href]') return (f.links || []).map(link => element(link.text, link.href));
      if (selector.includes('[id*="captcha"')) return f.challenge ? [element()] : [];
      if (selector.startsWith('[role=')) return f.alert ? [element(f.alert)] : [];
      if (selector.includes('.login-container')) return f.dialog ? [element()] : [];
      if (selector === '.login-btn') return f.button ? [element()] : [];
      if (selector.includes('.main-container .user')) return f.entry ? [element()] : [];
      throw new Error('Unexpected fixture selector');
    }
  };
  const context = {document, location:{origin:f.origin || 'https://www.xiaohongshu.com',
    pathname:f.path || '/explore'}, window:{__INITIAL_STATE__:f.initialState},
    URL, getComputedStyle:()=>({visibility:'visible',display:'block'})};
  return vm.runInNewContext('(' + input.script + ')()', context, {timeout:1000});
});
process.stdout.write(JSON.stringify(result));
"""


def test_actual_extraction_with_synthetic_dom_and_user_state_variants():
    account = "SECRET_ACCOUNT_ID_T03"
    logged = {"guest": False, "userId": account}
    fixtures = [
        {"initialState": {"user": {"userInfo": {"value": logged}}}},
        {"initialState": {"user": {"userInfo": {"_value": logged}}}},
        {"initialState": {"user": {"userInfo": {"guest": False}}}},
        {}, {"button": True},
        {"entry": True, "challenge": True, "initialState": {"user": {"userInfo": logged}}},
        {"initialState": {"user": {"userInfo": {
            "value": logged, "_value": {"guest": True, "userId": account}
        }}}},
        {"path": "/verification", "initialState": {"user": {"userInfo": logged}}},
        {"alert": "访问受限 SECRET_SESSION_T03", "initialState": {"user": {"userInfo": logged}}},
        {"origin": "https://foreign.invalid", "initialState": {"user": {"userInfo": logged}}},
        {"path": "/other", "initialState": {"user": {"userInfo": logged}}},
        {"links":[{"text":"我", "href":"/user/profile/" + account}],
         "initialState": {"user": {"userInfo": {"userId": account}}}},
        {"initialState": {"user": {"userInfo": {
            "value": logged, "_value": {"guest": False, "userId": "different-account"}
        }}}},
    ]
    node = Path(playwright.__file__).parent / "driver" / ("node.exe" if sys.platform == "win32" else "node")
    completed = subprocess.run(
        [str(node), "-e", NODE_FIXTURE],
        input=json.dumps({"script": LOGIN_OBSERVATION_SCRIPT, "fixtures": fixtures}),
        text=True, encoding="utf-8", capture_output=True, timeout=10, check=True,
    )
    values = json.loads(completed.stdout)
    observations = [parse_login_observation(value) for value in values]
    assert [o.state for o in observations] == [
        "AUTHENTICATED", "AUTHENTICATED", "AUTHENTICATED", "UNKNOWN", "LOGIN_REQUIRED",
        "VERIFICATION_REQUIRED", "LOGIN_REQUIRED", "VERIFICATION_REQUIRED",
        "VERIFICATION_REQUIRED", "UNKNOWN", "UNKNOWN", "AUTHENTICATED", "AUTHENTICATED",
    ]
    assert observations[0].identity.stable_id.get_secret_value() == account
    assert observations[2].identity.stable_id is None
    assert observations[-1].identity.stable_id is None  # Conflicting IDs are never guessed.
    assert "SECRET_" not in json.dumps([o.evidence.model_dump() for o in observations])
    assert "SECRET_" not in repr(observations)


@pytest.mark.parametrize("link", [
    {"text":"我", "href":"https://foreign.invalid/user/profile/PRIVATE_ACCOUNT"},
    {"text":"他人", "href":"/user/profile/PRIVATE_ACCOUNT"},
    {"text":"我", "href":"/user/profile/different-account"},
])
def test_unrelated_profile_link_cannot_authenticate(link):
    node = Path(playwright.__file__).parent / "driver" / ("node.exe" if sys.platform == "win32" else "node")
    fixture = {"links":[link], "initialState":{"user":{"userInfo":{"userId":"PRIVATE_ACCOUNT"}}}}
    completed = subprocess.run(
        [str(node), "-e", NODE_FIXTURE],
        input=json.dumps({"script":LOGIN_OBSERVATION_SCRIPT,"fixtures":[fixture]}),
        text=True, encoding="utf-8", capture_output=True, timeout=10, check=True,
    )
    assert parse_login_observation(json.loads(completed.stdout)[0]).state == "UNKNOWN"
