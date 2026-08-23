import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
OWNER = "pie-peb3-lab"
REPO = "pie-peb3-calibration"
FULL_NAME = f"{OWNER}/{REPO}"
PR_NUMBER = 1
EXPECTED_HEAD = "295d73c9b263280705fe0ad66cd96d0edc5ee47c"
APP_ID = os.environ["PEB3_APP_ID"]
PRIVATE_KEY = os.environ["PEB3_APP_PRIVATE_KEY"]
EVIDENCE_PATH = "peb3e-controlled-calibration-evidence.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def request_json(url, *, method="GET", token=None, data=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pie-peb3-controlled-calibration",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub HTTP {exc.code}: {body[:400]}") from exc


def graphql(token, query, variables):
    result = request_json(GRAPHQL, method="POST", token=token, data={"query": query, "variables": variables})
    if result.get("errors"):
        raise RuntimeError(f"GraphQL error: {json.dumps(result['errors'])[:400]}")
    return result["data"]


def mint_app_jwt():
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(APP_ID)}, separators=(",", ":")).encode())
    unsigned = f"{header}.{payload}".encode("ascii")
    with tempfile.NamedTemporaryFile("w", delete=False) as key_file:
        key_file.write(PRIVATE_KEY)
        key_path = key_file.name
    try:
        signature = subprocess.check_output(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=unsigned,
            stderr=subprocess.DEVNULL,
        )
    finally:
        os.unlink(key_path)
    return f"{unsigned.decode('ascii')}.{b64url(signature)}"


def get_target(token):
    pr = request_json(f"{API}/repos/{FULL_NAME}/pulls/{PR_NUMBER}", token=token)
    return {
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "head_sha": (pr.get("head") or {}).get("sha"),
        "node_id": pr.get("node_id"),
        "merged": pr.get("merged", False),
    }


def assert_target(snapshot, *, draft):
    if snapshot["state"] != "open":
        raise RuntimeError(f"target state drift: {snapshot}")
    if snapshot["merged"]:
        raise RuntimeError(f"target unexpectedly merged: {snapshot}")
    if snapshot["draft"] is not draft:
        raise RuntimeError(f"target draft pre/postcondition mismatch: {snapshot}")
    if snapshot["head_sha"] != EXPECTED_HEAD:
        raise RuntimeError(f"target HEAD drift: {snapshot['head_sha']}")
    if not snapshot["node_id"]:
        raise RuntimeError("target node_id missing")


def write_evidence(evidence):
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main():
    evidence = {
        "contract_version": "PEB3E_CONTROLLED_NONPRODUCTION_PR_STATE_CALIBRATION_V1",
        "provider": "GITHUB",
        "target": {
            "repository": FULL_NAME,
            "pr_number": PR_NUMBER,
            "expected_head_sha": EXPECTED_HEAD,
        },
        "authority_ceiling": {
            "production_execution_authorized": False,
            "automation_authorized": False,
            "pilot_authorized": False,
        },
        "started_at": now_iso(),
        "status": "STARTED",
        "dispatch": {"attempted": False},
        "rollback": {"attempted": False, "verified": False},
        "token_value_included": False,
    }
    token = None
    ready_applied = False
    try:
        app_jwt = mint_app_jwt()
        app = request_json(f"{API}/app", token=app_jwt)
        installations = request_json(f"{API}/app/installations", token=app_jwt)
        matches = [x for x in installations if (x.get("account") or {}).get("login") == OWNER]
        if len(matches) != 1:
            raise RuntimeError(f"expected one installation for {OWNER}, got {len(matches)}")
        installation = matches[0]
        if installation.get("repository_selection") != "selected":
            raise RuntimeError("installation repository_selection is not selected")

        token_response = request_json(
            f"{API}/app/installations/{installation['id']}/access_tokens",
            method="POST",
            token=app_jwt,
            data={"repositories": [REPO], "permissions": {"pull_requests": "write"}},
        )
        token = token_response.get("token")
        if not token:
            raise RuntimeError("installation token missing")
        repos = sorted((r.get("full_name") or "") for r in token_response.get("repositories", []))
        permissions = token_response.get("permissions") or {}
        if repos != [FULL_NAME]:
            raise RuntimeError(f"token repository scope mismatch: {repos}")
        if permissions.get("pull_requests") != "write":
            raise RuntimeError(f"token pull_requests permission mismatch: {permissions}")
        if set(permissions) - {"metadata", "pull_requests"}:
            raise RuntimeError(f"unexpected token permissions: {permissions}")
        if permissions.get("metadata") not in (None, "read"):
            raise RuntimeError(f"unexpected metadata permission: {permissions}")
        if not token_response.get("expires_at"):
            raise RuntimeError("token expiry missing")

        independent = request_json(f"{API}/installation/repositories", token=token)
        independent_repos = sorted((r.get("full_name") or "") for r in independent.get("repositories", []))
        if independent_repos != [FULL_NAME]:
            raise RuntimeError(f"independent token repository readback mismatch: {independent_repos}")

        evidence["credential"] = {
            "app_id": app.get("id"),
            "app_slug": app.get("slug"),
            "installation_id": installation.get("id"),
            "installation_account": (installation.get("account") or {}).get("login"),
            "repository_selection": installation.get("repository_selection"),
            "token_repository_set": repos,
            "token_permissions": permissions,
            "token_expires_at": token_response.get("expires_at"),
            "independent_repository_readback": independent_repos,
            "independent_repository_readback_verified": True,
        }

        before = get_target(token)
        assert_target(before, draft=True)
        evidence["pre_dispatch_readback"] = before

        mark_query = "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{id isDraft state}}}"
        evidence["dispatch"]["attempted"] = True
        evidence["dispatch"]["operation"] = "MARK_READY_FOR_REVIEW"
        graphql(token, mark_query, {"id": before["node_id"]})
        ready_applied = True

        ready_readback = get_target(token)
        assert_target(ready_readback, draft=False)
        evidence["dispatch"]["postcondition_readback"] = ready_readback
        evidence["dispatch"]["postcondition_verified"] = True

        draft_query = "mutation($id:ID!){convertPullRequestToDraft(input:{pullRequestId:$id}){pullRequest{id isDraft state}}}"
        evidence["rollback"]["attempted"] = True
        evidence["rollback"]["operation"] = "CONVERT_TO_DRAFT"
        graphql(token, draft_query, {"id": before["node_id"]})
        ready_applied = False

        final_readback = get_target(token)
        assert_target(final_readback, draft=True)
        evidence["rollback"]["postcondition_readback"] = final_readback
        evidence["rollback"]["verified"] = True
        evidence["final_target_state_restored"] = True
        evidence["status"] = "CONTROLLED_NON_PRODUCTION_CALIBRATION_PASS"
        evidence["completed_at"] = now_iso()
        write_evidence(evidence)
    except Exception as exc:
        evidence["status"] = "FAILED"
        evidence["error_class"] = type(exc).__name__
        evidence["error"] = str(exc)[:500]
        if token and ready_applied:
            evidence["rollback"]["attempted"] = True
            evidence["rollback"]["emergency"] = True
            try:
                current = get_target(token)
                node_id = current.get("node_id")
                if node_id:
                    draft_query = "mutation($id:ID!){convertPullRequestToDraft(input:{pullRequestId:$id}){pullRequest{id isDraft state}}}"
                    graphql(token, draft_query, {"id": node_id})
                    final = get_target(token)
                    assert_target(final, draft=True)
                    evidence["rollback"]["postcondition_readback"] = final
                    evidence["rollback"]["verified"] = True
                    evidence["final_target_state_restored"] = True
            except Exception as rollback_exc:
                evidence["rollback"]["error"] = str(rollback_exc)[:500]
                evidence["final_target_state_restored"] = False
        evidence["completed_at"] = now_iso()
        write_evidence(evidence)
        raise


if __name__ == "__main__":
    main()
