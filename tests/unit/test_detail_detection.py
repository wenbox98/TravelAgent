"""T04.1 detail evidence: synthetic Node VM only, no browser or external requests."""

import json
from pathlib import Path
import subprocess
import sys

import playwright
import pytest

from xhs_sidecar.detail_detection import (
    DETAIL_EVIDENCE_SCRIPT, DetailPageEvidence, classify_detail, detail_route, parse_detail_evidence,
)


def evidence(**changes):
    return DetailPageEvidence.model_validate({
        "route": "DETAIL_EXPLORE", "identity": "IDENTITY_MATCH", "page_ready": True,
        "login_present": False, "verification_present": False,
        "title_present": True, "body_present": True, **changes,
    })


@pytest.mark.parametrize("prefix,result", [
    ("explore", "DETAIL_EXPLORE"), ("search_result", "DETAIL_SEARCH_RESULT"),
])
def test_d01_two_same_identity_routes(prefix, result):
    for suffix in ("", "/", "?xsec_token=SECRET_T041"):
        assert detail_route(f"https://www.xiaohongshu.com/{prefix}/note-a{suffix}", "note-a") == result
    assert classify_detail(evidence(route=result), 200) == "DETAIL_EXPECTED"


@pytest.mark.parametrize("url,route", [
    ("https://foreign.invalid/explore/note-a", "FOREIGN_ORIGIN"),
    ("https://www.xiaohongshu.com.evil.invalid/explore/note-a", "FOREIGN_ORIGIN"),
    ("http://www.xiaohongshu.com/explore/note-a", "FOREIGN_ORIGIN"),
    ("https://www.xiaohongshu.com:8443/explore/note-a", "FOREIGN_ORIGIN"),
    ("https://secret@www.xiaohongshu.com/explore/note-a", "FOREIGN_ORIGIN"),
    ("https://www.xiaohongshu.com/explore/other", "OTHER_DETAIL_ID"),
    ("https://www.xiaohongshu.com/explore/note-a/extra", "UNEXPECTED_PAGE"),
    ("https://www.xiaohongshu.com/explore/note-a//", "UNEXPECTED_PAGE"),
    ("https://www.xiaohongshu.com/user/profile/author", "OTHER_OFFICIAL_PAGE"),
])
def test_d02_route_boundaries(url, route):
    assert detail_route(url, "note-a") == route
    assert classify_detail(evidence(route=route), 200) != "DETAIL_EXPECTED"


@pytest.mark.parametrize("changes,expected", [
    ({"login_present": True}, "LOGIN_REQUIRED"),
    ({"verification_present": True, "login_present": True}, "VERIFICATION_REQUIRED"),
    ({"identity": "IDENTITY_MISMATCH"}, "IDENTITY_MISMATCH"),
    ({"locator_invalid": True, "error_container_present": True}, "ACCESS_LOCATOR_INVALID"),
    ({"not_found": True}, "NOT_FOUND"),
    ({"identity": "UNKNOWN"}, "UNKNOWN"),
    ({"body_present": False}, "UNKNOWN"),
    ({"page_ready": False}, "UNKNOWN"),
    ({"login_present": None}, "UNKNOWN"),
])
def test_d03_to_d07_signals_and_negative_priority(changes, expected):
    assert classify_detail(evidence(**changes), 200) == expected


def test_d08_only_url_is_not_identity_or_detail_evidence():
    assert classify_detail(DetailPageEvidence(route="DETAIL_EXPLORE"), 200) == "UNKNOWN"


@pytest.mark.parametrize("status,expected", [
    (401, "ACCESS_DENIED"), (403, "ACCESS_DENIED"), (429, "ACCESS_DENIED"),
    (404, "NOT_FOUND"), (410, "NOT_FOUND"), (500, "UNEXPECTED_PAGE"),
    (503, "UNEXPECTED_PAGE"), (302, "UNEXPECTED_PAGE"),
])
def test_d09_failed_http_is_not_valid_detail_or_inferred_locator_expiry(status, expected):
    assert classify_detail(evidence(), status) == expected


NODE = r"""
const fs=require('node:fs'), vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const results=input.fixtures.map(f=>{
  const blocked=()=>{throw Error('Forbidden side effect or secret read');};
  const hidden=(obj,key)=>Object.defineProperty(obj,key,{get:blocked});
  const note={noteId:f.actualId||'note-a',title:'SECRET_TITLE',desc:'SECRET_BODY',
    user:{nickname:'SECRET_AUTHOR'},imageList:[{}]};
  hidden(note,'xsecToken'); hidden(note,'comments'); hidden(note.user,'userId');
  const map={'note-a':{note}}; hidden(map,'another-note');
  const window={};
  if(f.foreign) hidden(window,'__INITIAL_STATE__');
  else window.__INITIAL_STATE__=f.missing?{}:{note:{noteDetailMap:map}};
  const element=text=>({textContent:text,getClientRects:()=>[{}]});
  const document={title:'SECRET_DOCUMENT_TITLE',readyState:'complete',querySelectorAll(s){
    if(f.foreign) blocked();
    if(s.startsWith('.access-wrapper')&&f.error) return [element(f.error)];
    if(s==='.login-container, .qrcode-img, .login-btn'&&f.login) return [element('SECRET_LOGIN')];
    return [];
  }};
  hidden(document,'cookie');
  const context={window,document,location:{origin:f.foreign?'https://foreign.invalid':
    'https://www.xiaohongshu.com',pathname:f.path||'/explore/note-a'},
    getComputedStyle:()=>({display:'block',visibility:'visible'}),
    fetch:blocked,XMLHttpRequest:blocked,scrollTo:blocked,readId:'note-a'};
  return vm.runInNewContext('('+input.script+')(readId)',context,{timeout:1000});
});
process.stdout.write(JSON.stringify(results));
"""


def test_actual_script_multisignal_identity_and_secrets_without_legacy_root():
    node = Path(playwright.__file__).parent / "driver" / ("node.exe" if sys.platform == "win32" else "node")
    fixtures = [{}, {"path": "/search_result/note-a"}, {"actualId": "other"},
                {"foreign": True}, {"missing": True}, {"login": True},
                {"error": "链接已失效 SECRET_TOKEN"}, {"error": "安全验证 SECRET_TOKEN"}]
    result = subprocess.run([str(node), "-e", NODE], input=json.dumps({
        "script": DETAIL_EVIDENCE_SCRIPT, "fixtures": fixtures,
    }), text=True, encoding="utf-8", capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert "SECRET_" not in result.stdout
    values = [parse_detail_evidence(value) for value in json.loads(result.stdout)]
    assert [classify_detail(value, 200) for value in values] == [
        "DETAIL_EXPECTED", "DETAIL_EXPECTED", "IDENTITY_MISMATCH", "UNEXPECTED_PAGE",
        "UNKNOWN", "LOGIN_REQUIRED", "ACCESS_LOCATOR_INVALID", "VERIFICATION_REQUIRED",
    ]
    assert not any((values[0].root_note_container, values[0].root_note_detail, values[0].root_note_scroller))
    assert values[0].identity == "IDENTITY_MATCH" and values[0].map_entry_present
    assert parse_detail_evidence({"token": "SECRET_TOKEN"}) == DetailPageEvidence()
