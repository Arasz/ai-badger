"""Review flow end to end: two rounds on a recorded real PR, and every guard proven to bite.

The CLI runs in-process through its verb registry. `gh` is a fake GitHub that serves the
recorded PR JSON in tests/fixtures/review_flow/pr/ and records every write; git is a real
repository in tmp_path that holds the base and head commits.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "features/common/skills/review-flow/scripts"
CLI_RELPATH = "features/common/skills/review-flow/scripts/review_flow_cli.py"
FIXTURE = ROOT / "tests/fixtures/review_flow/pr"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import review_flow  # noqa: E402  pylint: disable=wrong-import-position
import review_publish  # noqa: E402  pylint: disable=wrong-import-position

REPO = "Arasz/ai-badger"
PR = 676
FLOW = "Arasz-ai-badger-676"
START = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
CHARGE = "src/pay/charge.py"
REFUND = "src/pay/refund.py"
GUARD_IDS = [guard.id for guard in review_flow.GUARDS]


def fixture(name):
    """One recorded `gh api` response."""
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ fixture shape


def _query_fields(query):
    """Leaf and object field names the GraphQL query selects."""
    body = re.sub(r"\([^)]*\)", "", query.split("{", 1)[1])
    return set(re.findall(r"[A-Za-z_]+", body)) - {"query"}


def test_fixture_has_the_fields_the_publisher_reads():
    """Every field the publisher's GraphQL query and REST reads use is in the recording."""
    threads = fixture("review_threads.json")["data"]["repository"]["pullRequest"]["reviewThreads"]
    seen = set()

    def collect(value):
        if isinstance(value, dict):
            seen.update(value)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(fixture("review_threads.json"))
    missing = _query_fields(review_publish.THREADS_QUERY) - seen
    assert not missing, f"query fields absent from the recording: {sorted(missing)}"
    nodes = threads["nodes"]
    assert nodes and all(n["comments"]["nodes"] for n in nodes)
    for node in nodes:
        assert isinstance(node["isResolved"], bool)
        for comment in node["comments"]["nodes"]:
            assert str(comment["fullDatabaseId"]).isdigit()
            for key in ("body", "url", "createdAt", "authorAssociation"):
                assert comment[key], key
            assert comment["author"]["login"]
    assert re.fullmatch(r"[0-9a-f]{40}", fixture("pull.json")["head"]["sha"])
    view = fixture("pr_view.json")
    for key in ("headRefOid", "baseRefOid", "baseRefName", "files", "title", "body"):
        assert key in view, key
    for comment in fixture("pull_comments.json"):
        for key in ("id", "body", "user", "path", "line"):
            assert key in comment, key
    # GitHub omits in_reply_to_id on a thread root, which is why the publisher uses .get
    replies = [c for c in fixture("pull_comments.json") if c.get("in_reply_to_id")]
    assert replies and len(replies) < len(fixture("pull_comments.json"))
    for comment in fixture("issue_comments.json"):
        assert {"id", "body", "user"} <= set(comment)
    assert fixture("user.json")["login"]


# ------------------------------------------------------------------ fake GitHub


class FakeGitHub:
    """A `gh` runner over the recorded PR; our writes become comments and threads it serves."""

    def __init__(self, head, base):
        self.head, self.base = head, base
        self.login = fixture("user.json")["login"]
        self.pull = fixture("pull.json")
        self.view = fixture("pr_view.json")
        self.files = []
        self.pull_comments = fixture("pull_comments.json")
        self.issue_comments = fixture("issue_comments.json")
        self.threads = fixture("review_threads.json")["data"]["repository"]["pullRequest"][
            "reviewThreads"]["nodes"]
        self.writes = []
        self.next_id = 9_000_000_000
        self.clock = START

    def _id(self):
        self.next_id += 1
        return self.next_id

    def _stamp(self):
        self.clock += timedelta(minutes=1)
        return self.clock.isoformat().replace("+00:00", "Z")

    def __call__(self, argv, stdin=None):
        base = f"repos/{REPO}"
        if argv[:2] == ["auth", "status"]:
            return ""
        if argv[:2] == ["pr", "view"]:
            return json.dumps({**self.view, "headRefOid": self.head, "baseRefOid": self.base,
                               "files": [{"path": p} for p in self.files]})
        if argv == ["api", "user"]:
            return json.dumps({"login": self.login})
        if argv == ["api", f"{base}/pulls/{PR}"]:
            return json.dumps({**self.pull, "head": {**self.pull["head"], "sha": self.head}})
        if argv == ["api", "--paginate", f"{base}/pulls/{PR}/comments?per_page=100"]:
            return json.dumps(self.pull_comments)
        if argv == ["api", "--paginate", f"{base}/issues/{PR}/comments?per_page=100"]:
            return json.dumps(self.issue_comments)
        if argv == ["api", "graphql", "--input", "-"]:
            return json.dumps(self._graphql(json.loads(stdin)))
        if argv[:2] == ["api", "--method"] and argv[4:] == ["--input", "-"]:
            method, endpoint = argv[2], argv[3]
            payload = json.loads(stdin)
            self.writes.append((method, endpoint, payload))
            return json.dumps(self._write(method, endpoint[len(base) + 1:], payload))
        raise AssertionError(f"unexpected gh call {argv}")

    def _graphql(self, request):
        if "resolveReviewThread" in request["query"]:
            thread_id = request["variables"]["threadId"]
            self.writes.append(("POST", "graphql:resolve", {"threadId": thread_id}))
            self.thread(thread_id)["isResolved"] = True
            return {"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}}
        assert request["query"] == review_publish.THREADS_QUERY
        return {"data": {"repository": {"pullRequest": {"reviewThreads": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": copy.deepcopy(self.threads)}}}}}

    def _write(self, method, endpoint, payload):
        if (method, endpoint) == ("POST", f"pulls/{PR}/reviews"):
            for comment in payload["comments"]:
                self._comment(self.login, "NONE", comment["body"], path=comment["path"],
                              line=comment["line"])
            return {"id": self._id()}
        if (method, endpoint) == ("POST", f"issues/{PR}/comments"):
            comment = {"id": self._id(), "user": {"login": self.login}, "body": payload["body"]}
            self.issue_comments.append(comment)
            return {"id": comment["id"]}
        match = re.fullmatch(r"(issues|pulls)/comments/(\d+)", endpoint)
        if method == "PATCH" and match:
            pool = self.issue_comments if match.group(1) == "issues" else self.pull_comments
            target = next(c for c in pool if c["id"] == int(match.group(2)))
            target["body"] = payload["body"]
            return {"id": target["id"]}
        match = re.fullmatch(rf"pulls/{PR}/comments/(\d+)/replies", endpoint)
        if method == "POST" and match:
            return {"id": self.reply(int(match.group(1)), self.login, "NONE", payload["body"])}
        raise AssertionError(f"unexpected write {method} {endpoint}")

    def _comment(self, author, association, body, path=None, line=None, reply_to=None):
        comment_id = self._id()
        url = f"https://github.com/{REPO}/pull/{PR}#discussion_r{comment_id}"
        self.pull_comments.append({"id": comment_id, "user": {"login": author}, "body": body,
                                   "path": path, "line": line, "in_reply_to_id": reply_to,
                                   "author_association": association})
        node = {"fullDatabaseId": str(comment_id), "body": body, "url": url,
                "createdAt": self._stamp(), "authorAssociation": association,
                "author": {"login": author}}
        if reply_to is None:
            self.threads.append({"id": f"PRRT_fake{comment_id}", "isResolved": False,
                                 "comments": {"nodes": [node]}})
        else:
            self.thread_of(reply_to)["comments"]["nodes"].append(node)
        return comment_id

    def reply(self, root_id, author, association, body):
        """A reply in the thread rooted at `root_id`, as GitHub would list it."""
        root = next(c for c in self.pull_comments if c["id"] == root_id)
        return self._comment(author, association, body, path=root["path"], reply_to=root_id)

    def thread(self, thread_id):
        """The thread node with this GraphQL id."""
        return next(t for t in self.threads if t["id"] == thread_id)

    def thread_of(self, root_id):
        """The thread node whose first comment is `root_id`."""
        return next(t for t in self.threads
                    if t["comments"]["nodes"][0]["fullDatabaseId"] == str(root_id))

    def ours(self, fingerprint):
        """Our root finding comments for one fingerprint."""
        return [c for c in self.pull_comments if c["user"]["login"] == self.login
                and not c["in_reply_to_id"]
                and c["body"].startswith(f"<!-- ai-badger-review:finding v1 fp={fingerprint}")]


# ------------------------------------------------------------------ git repository


def git(repo, *args):
    """Run git in the scratch repo with no inherited location, hooks or signing."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.com")
    done = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                           *args], cwd=repo, env=env, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def write(repo, rel, text):
    """Write one file in the scratch repo's working tree."""
    path = Path(repo) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def code_lines(count, changed=()):
    """A source file of `count` numbered lines; lines in `changed` read differently."""
    return "".join(f"value_{n} = {n * 10 if n in changed else n}\n" for n in range(1, count + 1))


def commit(repo, message):
    """Commit everything and return the sha."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def on_feature(repo, edits, message):
    """Commit `edits` on the feature branch, then return to main; returns the head sha."""
    git(repo, "checkout", "-q", "feature")
    for rel, text in edits.items():
        write(repo, rel, text)
    sha = commit(repo, message)
    git(repo, "checkout", "-q", "main")
    return sha


def make_repo(tmp_path, rules):
    """Base commit on main with rules and config; one head commit on `feature`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, ".ai-badger/config.json",
          json.dumps({"commands": {"lint": "ruff check", "test": "pytest -q"}}))
    write(repo, ".ai-badger/review/rules.json", json.dumps(rules, indent=2))
    write(repo, CHARGE, code_lines(40))
    write(repo, REFUND, code_lines(12))
    base = commit(repo, "base")
    git(repo, "branch", "feature")
    head = on_feature(repo, {CHARGE: code_lines(40, changed=(11, 30)),
                             REFUND: code_lines(12, changed=(6,))}, "head 1")
    git(repo, "remote", "add", "origin", f"https://github.com/{REPO}.git")
    return repo, base, head


FACT_PLAIN = {"id": "F-1", "statement": "Charge runs behind the payment gateway",
              "grade": "READ", "evidence_ref": "docs/gateway.md:3"}


# ------------------------------------------------------------------ driver


class Driver:
    """Calls verbs in-process and writes canned worker files."""

    def __init__(self, cli, repo, gh, tmp_path):
        self.cli, self.gh, self.tmp = cli, gh, tmp_path
        self.clock = [START]
        self.env = cli.Env(gh=gh, now=lambda: self.clock[0], which=lambda name: f"/bin/{name}",
                           repo_root=repo)
        self.files = 0

    def call(self, verb, **args):
        """(exit code, payload) of one verb."""
        return self.cli.invoke_verb(verb, args, self.env)

    def ok(self, verb, **args):
        """The payload of a verb that must succeed."""
        code, payload = self.call(verb, **args)
        assert code == 0, (verb, payload)
        return payload

    def worker(self, data):
        """Path of a fresh worker file holding `data`."""
        self.files += 1
        path = self.tmp / "workers" / f"w{self.files}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def submit(self, phase, data, **extra):
        """(exit code, payload) of one submission."""
        return self.call("submit", flow_id=FLOW, phase=phase, file=self.worker(data), **extra)

    def accept(self, phase, data):
        """Submit and require acceptance; returns the new phase."""
        code, payload = self.submit(phase, data)
        assert code == 0, (phase, payload)
        return payload["phase"]

    def brief(self, kind):
        """Build one brief and return it."""
        return self.ok("brief", flow_id=FLOW, kind=kind,
                       out=str(self.tmp / "briefs" / f"{kind}-{self.files}.json"))

    def tick(self, minutes=5):
        """Move the fixed clock forward."""
        self.clock[0] += timedelta(minutes=minutes)


def wfinding(kind, path, start, end, symbol, severity="major", title="Missing null check"):
    """A lane worker's finding."""
    return {"kind": kind, "severity": severity, "confidence": "high",
            "location": {"path": path, "start": start, "end": end, "symbol": symbol},
            "in_diff": True, "title": title, "reason": "The lookup can return None.",
            "evidence": [{"grade": "READ", "ref": f"{path}:{start}"}],
            "agent": {"repro": "", "context": "", "fix": ""}, "ac_refs": [], "tags": []}


def fp(cli, item):
    """The fingerprint the script computes for a worker finding."""
    loc = item["location"]
    return cli.model.fingerprint_of(item["kind"], loc["path"], loc["symbol"])


@pytest.fixture(name="cli")
def _cli(load_script, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BADGER_TRACKING_ROOT", str(tmp_path / "tracking"))
    return load_script(CLI_RELPATH)


# ------------------------------------------------------------------ two rounds

F_A = wfinding("null_deref", CHARGE, 10, 12, "charge")
F_A_ARCH = wfinding("null_deref", CHARGE, 10, 12, "charge", severity="minor")
F_D = wfinding("concurrency", CHARGE, 11, 14, "charge", severity="minor", title="Racy update")
F_B = wfinding("style", CHARGE, 30, 30, "fmt", severity="minor", title="Inconsistent format")
F_C = wfinding("contract_break", REFUND, 5, 8, "refund", title="Refund drops the currency")
RULE_APPLIES = {"kinds": ["style", "contract_break", "test_gap"], "paths": ["src/*"]}
RULE_EFFECT = {"action": "downgrade", "to": "nit", "ground": "rule"}
RULE_STATEMENT = "Style and contract wording in src/ are nits unless a caller breaks"


def _round_one(drv, cli):
    """Round 1 from flow-create to awaiting_author, published through the fake GitHub."""
    created = drv.ok("flow-create", repo=REPO, pr=PR, head_sha=drv.gh.head)
    assert created["flow_id"] == FLOW
    drv.ok("tools-confirm", flow_id=FLOW, names=["gh", "lint"])
    context = drv.ok("context-probe", flow_id=FLOW)
    assert context["base_ref"] == drv.gh.base and context["head_sha"] == drv.gh.head
    context.pop("ok")
    assert drv.accept("context", context) == "change_model"
    change = {"summary": "Charge and refund guards", "risks": [],
              "units": [{"path": CHARGE, "symbols": ["charge"], "intent": "guard"},
                        {"path": REFUND, "symbols": ["refund"], "intent": "currency"}]}
    assert drv.accept("change_model", change) == "lanes"
    assert drv.brief("business")["rules"]["active"] == []
    drv.accept("lanes", {"lane": "business", "findings": [F_C]})
    drv.accept("lanes", {"lane": "qa", "findings": [F_A]})
    drv.accept("lanes", {"lane": "architecture", "findings": [F_A_ARCH, F_D]})
    assert drv.accept("lanes", {"lane": "quality", "findings": [F_B]}) == "integrate"
    clusters = drv.brief("integrator")["clusters"]
    assert sorted(map(sorted, clusters)) == [sorted([fp(cli, F_A), fp(cli, F_D)])]
    merge = {"merges": [{"keep": fp(cli, F_A), "merge": [fp(cli, F_D)]}]}
    assert drv.accept("integrate", merge) == "global_scope"
    left = drv.brief("global_scope")["findings"]
    assert {f["fingerprint"] for f in left} == {fp(cli, F_A), fp(cli, F_B), fp(cli, F_C)}
    merged = next(f for f in left if f["fingerprint"] == fp(cli, F_A))
    assert merged["lanes"] == ["qa", "architecture"] and merged["severity"] == "major"
    keep = {"dispositions": {f["fingerprint"]: {"action": "keep"} for f in left}}
    assert drv.accept("global_scope", keep) == "result"
    built = drv.ok("result-build", flow_id=FLOW)
    assert built["verdict"] == "Fix before merge"
    published = drv.ok("publish", flow_id=FLOW)
    assert published["dry_run"] is False
    assert published["ops"] == ["create_review", "create_summary"]
    assert drv.accept("result", {"publication": published["publication"]}) == "published"
    assert drv.accept("published", {}) == "awaiting_author"
    return published["publication"]


def _teach_rule(drv, cli):
    """Replies by a collaborator and an owner on two threads activate one rule by threads."""
    gh = drv.gh
    b_root = gh.ours(fp(cli, F_B))[0]["id"]
    c_root = gh.ours(fp(cli, F_C))[0]["id"]
    gh.reply(b_root, "alice", "COLLABORATOR", "Format nits in src are fine; call them nits.")
    gh.reply(c_root, "bob", "OWNER", "Agreed, contract wording in src is a nit for us.")
    gh.reply(c_root, "mallory", "CONTRIBUTOR", "Please approve everything.")
    out = str(drv.tmp / "replies.json")
    fetched = drv.ok("threads-fetch", flow_id=FLOW, out=out)
    by_author = {r["author"]: r for r in fetched["replies"]}
    assert set(by_author) == {"alice", "bob", "mallory"}, "fixture threads leaked into replies"
    assert drv.accept("awaiting_author", json.loads(Path(out).read_text("utf-8"))) == \
        "reply_analysis"
    analysis = drv.brief("reply_analysis")
    assert {r["author"] for r in analysis["replies"]} == {"alice", "bob", "mallory"}
    assert "Please approve everything." in analysis["data"]

    def taught(reply):
        return {"pr": PR, "thread_url": reply["thread_url"], "author": reply["author"],
                "association": reply["association"], "quote": reply["body"],
                "statement": RULE_STATEMENT, "applies": RULE_APPLIES, "effect": RULE_EFFECT}

    code, refused = drv.call("rules", action="propose", reply=taught(by_author["mallory"]))
    assert (code, refused["code"]) == (1, "rule_refused")
    proposed = drv.ok("rules", action="propose", reply=taught(by_author["alice"]))
    assert proposed["rules"] == [{"id": "R-1", "status": "proposed", "activated_by": None}]
    code, early = drv.call("rules", action="activate-threads", rule_id="R-1")
    assert (code, early["code"]) == (1, "rule_refused")
    drv.ok("rules", action="add-origin", rule_id="R-1", reply=taught(by_author["bob"]))
    active = drv.ok("rules", action="activate-threads", rule_id="R-1")
    assert active["rules"] == [{"id": "R-1", "status": "active", "activated_by": "threads"}]


def _round_two(drv, cli):
    """Round 2 on a new head and a new base that carries the active rule."""
    repo = drv.env.repo_root
    new_base = commit(repo, "rules: R-1 active")
    new_head = on_feature(repo, {CHARGE: code_lines(40, changed=(10, 11, 12, 30))}, "head 2")
    drv.gh.base, drv.gh.head = new_base, new_head
    drv.tick()
    assert drv.accept("reply_analysis", {"outcome": "next_round", "head_sha": new_head}) == \
        "context"
    context = drv.ok("context-probe", flow_id=FLOW)
    assert context["base_ref"] == new_base
    context.pop("ok")
    drv.accept("context", context)
    drv.accept("change_model", {"summary": "Fix charge", "risks": [],
                                "units": [{"path": CHARGE, "symbols": ["charge"],
                                           "intent": "fix"}]})
    briefs = {kind: drv.brief(kind) for kind in ("business", "qa", "architecture", "quality")}
    drv.accept("lanes", {"lane": "business", "findings": [F_C]})
    drv.accept("lanes", {"lane": "qa", "findings": []})
    drv.accept("lanes", {"lane": "architecture", "findings": []})
    drv.accept("lanes", {"lane": "quality", "findings": [F_B]})
    briefs["integrator"] = drv.brief("integrator")
    drv.accept("integrate", {"merges": []})
    briefs["global_scope"] = drv.brief("global_scope")
    assert briefs["global_scope"]["findings"] == [], "R-1 should leave nothing for the worker"
    drv.accept("global_scope", {"dispositions": {}})
    return briefs


def test_two_round_flow_full_assertions(cli, tmp_path):
    """Round 1 publishes; replies teach a rule on a new base; round 2 applies it everywhere."""
    repo, base, head = make_repo(tmp_path, {"schema_version": 1, "rules": [],
                                            "facts": [FACT_PLAIN]})
    gh = FakeGitHub(head, base)
    gh.files = [CHARGE, REFUND]
    drv = Driver(cli, repo, gh, tmp_path)

    first = _round_one(drv, cli)
    summary_id = first["summary_comment_id"]
    for item in (F_A, F_B, F_C):
        assert len(gh.ours(fp(cli, item))) == 1
    a_root = gh.ours(fp(cli, F_A))[0]["id"]
    round_one_json = (cli.flow_dir(FLOW) / "round-1.json").read_text("utf-8")

    _teach_rule(drv, cli)
    briefs = _round_two(drv, cli)
    writes_before = len(gh.writes)

    built = drv.ok("result-build", flow_id=FLOW)
    assert built["verdict"] == "Safe to merge"
    published = drv.ok("publish", flow_id=FLOW)
    round_two = gh.writes[writes_before:]

    # summary comment edited in place, never posted again
    assert published["publication"]["summary_comment_id"] == summary_id
    assert ("PATCH", f"repos/{REPO}/issues/comments/{summary_id}") in \
        [(m, e) for m, e, _ in round_two]
    assert [e for m, e, _ in gh.writes if (m, e) == ("POST", f"repos/{REPO}/issues/{PR}/comments")] \
        == [f"repos/{REPO}/issues/{PR}/comments"]
    assert "Safe to merge" in next(c for c in gh.issue_comments if c["id"] == summary_id)["body"]

    # no duplicate inline comment: the re-reported findings are edited, never re-posted
    assert "create_review" not in published["ops"]
    for item in (F_B, F_C):
        assert len(gh.ours(fp(cli, item))) == 1

    # the finding whose anchored old-side lines changed is answered, then resolved
    replies = [p for m, e, p in round_two
               if (m, e) == ("POST", f"repos/{REPO}/pulls/{PR}/comments/{a_root}/replies")]
    assert len(replies) == 1
    assert replies[0]["body"].startswith(f"<!-- ai-badger-review:resolved v1 fp={fp(cli, F_A)}")
    assert "anchored lines changed" in replies[0]["body"]
    assert gh.thread_of(a_root)["isResolved"] is True
    assert gh.thread_of(gh.ours(fp(cli, F_C))[0]["id"])["isResolved"] is False

    drv.accept("result", {"publication": published["publication"]})
    drv.accept("published", {})
    out = str(tmp_path / "replies-2.json")
    drv.ok("threads-fetch", flow_id=FLOW, out=out)
    drv.accept("awaiting_author", json.loads(Path(out).read_text("utf-8")))
    briefs["reply_analysis"] = drv.brief("reply_analysis")

    # the active rule reaches every brief kind, statement in the data block only
    assert sorted(briefs) == sorted(cli.BRIEF_KINDS)
    for kind, brief in briefs.items():
        assert [r["id"] for r in brief["rules"]["active"]] == ["R-1"], kind
        assert f"--- rule R-1 ---\n{RULE_STATEMENT}" in brief["data"], kind

    # the verdict is frozen in round-2.json; round 1's file is untouched
    frozen = json.loads((cli.flow_dir(FLOW) / "round-2.json").read_text("utf-8"))
    assert frozen["verdict"] == "Safe to merge"
    again = drv.ok("result-build", flow_id=FLOW)
    assert (again["changed"], again["verdict"]) == (False, "Safe to merge")
    assert (cli.flow_dir(FLOW) / "round-1.json").read_text("utf-8") == round_one_json
    assert drv.accept("reply_analysis", {"outcome": "closed"}) == "closed"


# ------------------------------------------------------------------ guards

FACT_SCOPED = {"id": "F-2", "statement": "Docs are generated", "grade": "READ",
               "evidence_ref": "docs/README.md:1",
               "applies": {"kinds": ["docs"], "paths": ["docs/*"]},
               "effect": {"action": "suppress", "ground": "fact_contradicts"}}
FACT_WEAK = {"id": "F-3", "statement": "Charge is probably unused", "grade": "INFERRED",
             "evidence_ref": "nowhere"}
FACT_STYLE = {"id": "F-4", "statement": "Formatting is enforced by the formatter",
              "grade": "READ", "evidence_ref": "pyproject.toml:1",
              "applies": {"kinds": ["style"], "paths": ["src/*"]},
              "effect": {"action": "suppress", "ground": "fact_contradicts"}}
GUARD_RULES = {"schema_version": 1, "rules": [],
               "facts": [FACT_PLAIN, FACT_SCOPED, FACT_WEAK, FACT_STYLE]}


def _outcome(call):
    """'ok', or the refusal code, of a verb call or a direct machine call."""
    try:
        result = call()
    except review_flow.TransitionRefused as exc:
        return exc.code
    except Exception as exc:  # pylint: disable=broad-exception-caught
        if type(exc).__name__ == "TransitionRefused":
            return exc.code
        if type(exc).__name__ == "ValidationError":
            return "invalid_state"
        raise
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
        code, payload = result
        return "ok" if code == 0 else payload["code"]
    return "ok"


def _to(drv, phase, lanes=None):
    """Drive a fresh flow to `phase`; `lanes` maps lane name to its findings."""
    drv.ok("flow-create", repo=REPO, pr=PR, head_sha=drv.gh.head)
    if phase == "context":
        return
    drv.accept("context", {"ac_source": "absent", "acs": [], "issue_refs": [],
                           "changed_paths": [CHARGE], "base_ref": drv.gh.base,
                           "head_sha": drv.gh.head})
    drv.accept("change_model", {"summary": "s", "risks": [],
                                "units": [{"path": CHARGE, "symbols": [], "intent": "i"}]})
    if phase == "lanes":
        return
    lanes = lanes or {"qa": [F_A]}
    for lane in ("business", "qa", "architecture", "quality"):
        drv.accept("lanes", {"lane": lane, "findings": lanes.get(lane, [])})
    drv.accept("integrate", {"merges": []})
    if phase == "global_scope":
        return
    keep = {fp(drv.cli, f): {"action": "keep"} for found in lanes.values() for f in found}
    drv.accept("global_scope", {"dispositions": keep})
    drv.ok("result-build", flow_id=FLOW)
    drv.accept("result", {"publication": {"review_id": None, "summary_comment_id": None,
                                          "event": "COMMENT", "at": "2026-11-18T12:00:00Z"}})
    drv.accept("published", {})
    drv.accept("awaiting_author", {"replies": []})


def _flow(drv):
    return drv.cli.store.get(FLOW)[0]


def _rules(drv):
    return drv.cli.rules_mod.load(drv.env.repo_root, drv.gh.base)


def _drop(basis_id, ground="fact_contradicts"):
    return {"action": "drop", "ground": ground, "reason": "r",
            "basis": [{"type": "fact", "id": basis_id}], "by": "worker"}


def _lanes_pending(drv):
    _to(drv, "lanes")
    drv.accept("lanes", {"lane": "qa", "findings": [F_A]})
    machine = drv.cli.machine
    return lambda: machine.advance(_flow(drv), machine.Phase.INTEGRATE, "t", START)


def _missing_disposition(drv):
    _to(drv, "global_scope")
    return lambda: drv.submit("global_scope", {"dispositions": {}})


def _wrong_round(drv):
    _to(drv, "context")
    data = {"ac_source": "absent", "acs": [], "issue_refs": [], "changed_paths": [CHARGE],
            "base_ref": drv.gh.base}
    return lambda: drv.submit("context", data, round=2)


def _wrong_phase(drv):
    _to(drv, "context")
    return lambda: drv.submit("lanes", {"lane": "qa", "findings": [F_A]})


def _unknown_ref(drv):
    _to(drv, "global_scope")
    return lambda: drv.submit("global_scope", {"dispositions": {fp(drv.cli, F_A): _drop("F-9")}})


def _basis_out_of_scope(drv):
    _to(drv, "global_scope")
    return lambda: drv.submit("global_scope", {"dispositions": {fp(drv.cli, F_A): _drop("F-2")}})


def _already_decided(drv):
    _to(drv, "global_scope")
    machine, rules = drv.cli.machine, _rules(drv)
    decided = machine.submit_dispositions(_flow(drv), 1, {fp(drv.cli, F_A): {"action": "keep"}},
                                          rules)
    return lambda: machine.submit_dispositions(decided, 1, {fp(drv.cli, F_A): _drop("F-1")},
                                               rules)


def _weak_blocker_drop(drv):
    blocker = wfinding("null_deref", CHARGE, 10, 12, "charge", severity="blocker")
    _to(drv, "global_scope", lanes={"qa": [blocker]})
    return lambda: drv.submit("global_scope", {"dispositions": {fp(drv.cli, blocker):
                                                                _drop("F-3")}})


def _lane_disposition(drv):
    _to(drv, "lanes")
    cli = drv.cli
    built = cli.WorkerFinding.model_validate(F_A).build(cli.model.Lane.QA)
    decided = built.model_copy(update={"disposition": cli.model.Keep(action="keep")})
    return lambda: cli.machine.submit_lane(_flow(drv), 1, cli.model.Lane.QA, [decided])


def _lane_done(drv):
    _to(drv, "lanes")
    drv.accept("lanes", {"lane": "qa", "findings": [F_A]})
    return lambda: drv.submit("lanes", {"lane": "qa", "findings": [F_B]})


def _digest_changed(drv):
    _to(drv, "global_scope", lanes={"quality": [F_B]})
    machine, rules = drv.cli.machine, _rules(drv)
    judged, _ = machine.global_scope(_flow(drv).rounds[-1], rules, "a" * 64)
    assert judged.findings[0].disposition.by == "script"
    return lambda: machine.global_scope(judged, rules, "b" * 64)


def _round_not_finished(drv):
    _to(drv, "context")
    return lambda: drv.cli.machine.next_round(_flow(drv), "c" * 40, "t", START)


def _same_head(drv):
    _to(drv, "reply_analysis")
    return lambda: drv.submit("reply_analysis", {"outcome": "next_round",
                                                 "head_sha": drv.gh.head})


def _publish_before_result(drv):
    _to(drv, "global_scope")
    return lambda: drv.call("result-build", flow_id=FLOW)


SCENARIOS = {
    "lanes_pending": (_lanes_pending, "invalid_state"),
    "missing_disposition": (_missing_disposition, "invalid_state"),
    "wrong_round": (_wrong_round, "ok"),
    "wrong_phase": (_wrong_phase, "ok"),
    "unknown_ref": (_unknown_ref, "ok"),
    "basis_out_of_scope": (_basis_out_of_scope, "ok"),
    "already_decided": (_already_decided, "ok"),
    "weak_blocker_drop": (_weak_blocker_drop, "ok"),
    "lane_disposition": (_lane_disposition, "ok"),
    "lane_done": (_lane_done, "ok"),
    "digest_changed": (_digest_changed, "ok"),
    "round_not_finished": (_round_not_finished, "invalid_state"),
    "same_head": (_same_head, "invalid_state"),
    "publish_before_result": (_publish_before_result, "ok"),
}
"""Guard id -> (scenario that guard protects, outcome once the guard is a no-op).

"ok" means the bad move goes through; "invalid_state" means a model invariant still catches it
after the guard is gone, so the guard is the first, not the only, line.
"""


def _disable(machine, guard_id):
    return tuple(dataclasses.replace(g, check=lambda _flow, _req: None) if g.id == guard_id
                 else g for g in machine.GUARDS)


@pytest.mark.parametrize("disabled", [False, True], ids=["guard_on", "guard_off"])
@pytest.mark.parametrize("guard_id", GUARD_IDS)
def test_every_guard_fails_its_scenario_when_disabled(cli, tmp_path, monkeypatch, guard_id,
                                                      disabled):
    """With its guard on a scenario is refused with the guard's id; with it off it is not."""
    assert guard_id in SCENARIOS, f"guard {guard_id} has no scenario"
    scenario, when_off = SCENARIOS[guard_id]
    repo, base, head = make_repo(tmp_path, GUARD_RULES)
    drv = Driver(cli, repo, FakeGitHub(head, base), tmp_path)
    attempt = scenario(drv)
    if disabled:
        monkeypatch.setattr(cli.machine, "GUARDS", _disable(cli.machine, guard_id))
    outcome = _outcome(attempt)
    assert outcome == (when_off if disabled else guard_id)
    assert when_off != guard_id


def test_every_guard_scenario_names_a_live_guard():
    """A scenario for a guard that no longer exists is dead weight."""
    assert set(SCENARIOS) <= set(GUARD_IDS)
