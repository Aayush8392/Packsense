"""Rotate the OAuth secrets of the four Databricks service principals with one command (A1).

  python p3_delivery/bootstrap/rotate_principal_secrets.py plan   --env-file .env [--principal NAME ... | --all]
  python p3_delivery/bootstrap/rotate_principal_secrets.py rotate --env-file .env [--principal NAME ... | --all] [--lifetime-days 90] [--keep-old]
  python p3_delivery/bootstrap/rotate_principal_secrets.py show-expiry --env-file .env
  python p3_delivery/bootstrap/rotate_principal_secrets.py set-expiry NAME YYYY-MM-DD|null --env-file .env

Per principal, in this order (the OLD secret stays valid until the last step, so any failure leaves a working system):
  1 create a new OAuth secret (a principal may hold up to five, so the two overlap and nothing goes down)
  2 verify that the new secret really signs in as that principal
  3 gold principals only: write it into their Databricks secret scope (`oauth_client_secret`)
  4 write it into the GitHub environment secret `DATABRICKS_CLIENT_SECRET` (GitHub never returns a secret: the proof is that its
    `updated_at` moved, and then a manual deploy run)
  5 move the principal's entry in the repository variable SECRET_EXPIRY_LIST to the new expiry date
  6 delete the old secret(s) (skipped with --keep-old)
Only names, dates and ids are printed, never a value. Needs in the environment (or the env file): DATABRICKS_HOST, DATABRICKS_TOKEN (admin),
GITHUB_ROTATION_TOKEN (fine-grained, this repo only: Secrets and Variables read and write, Environments read). A stale DATABRICKS_CLIENT_ID/SECRET in the shell is dropped.
`plan` changes nothing. A re-run after a failure creates another secret (the limit is five per principal; the script stops at four).
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

REPO = "Aayush8392/Packsense"
EXPIRY_VARIABLE = "SECRET_EXPIRY_LIST"
SECRET_NAME = "DATABRICKS_CLIENT_SECRET"
SCOPE_KEY = "oauth_client_secret"
DEFAULT_LIFETIME_DAYS = 90
MAX_LIFETIME_DAYS = 730          # Databricks' documented maximum
MAX_SECRETS = 5                  # per principal; the script refuses to start at four so a re-run still fits

# Client ids are not secrets (they are in the public P3 README). Dev first: a failure stops before production.
PRINCIPALS = {
    "packsense-deployer-dev": {"client_id": "2e1246f9-63d0-4a91-91bb-e2b628348789", "github_env": "dev", "scope": None},
    "packsense-gold-dev": {"client_id": "05620ebf-cd4d-4b0a-88ad-029915441965", "github_env": "dev-gold", "scope": "packsense_gold_dev"},
    "packsense-deployer": {"client_id": "4fdd8310-bedc-4a22-8a94-bf436118e3e5", "github_env": "prod", "scope": None},
    "packsense-gold": {"client_id": "520fb1ac-a6cf-4913-b7af-c081eb32456c", "github_env": "prod-gold", "scope": "packsense_gold"},
}


# ---- pure logic (unit-tested) ------------------------------------------------------------------------------------------------

def lifetime_string(days: int) -> str:
    if not isinstance(days, int) or not 1 <= days <= MAX_LIFETIME_DAYS:
        raise ValueError(f"lifetime must be between 1 and {MAX_LIFETIME_DAYS} days")
    return f"{days * 86400}s"


def parse_expire_time(text: str) -> dt.date:
    """The date part of Databricks' ISO timestamp ('2027-01-17T09:12:03.123Z')."""
    return dt.date.fromisoformat(str(text)[:10])


def encrypt_for_github(public_key_b64: str, value: str) -> str:
    """GitHub's secret format: a libsodium sealed box under the repository's public key, base64."""
    from nacl.public import PublicKey, SealedBox
    return base64.b64encode(SealedBox(PublicKey(base64.b64decode(public_key_b64))).encrypt(value.encode("utf-8"))).decode("ascii")


def match_expiry_entry(entries: list, principal: str, override: str | None = None) -> str:
    """The entry of SECRET_EXPIRY_LIST that belongs to a principal: an override name, else the one entry that contains the principal's
    name as a whole hyphen-delimited word ('packsense-deployer' does not match 'packsense-deployer-dev'). Zero or several matches is an error."""
    names = [e["name"] for e in entries]
    if override:
        if override not in names:
            raise ValueError(f"--expiry-name {override!r} is not in {EXPIRY_VARIABLE}")
        return override
    rx = re.compile(r"(?<![\w-])" + re.escape(principal) + r"(?![\w-])", re.IGNORECASE)
    hits = [n for n in names if rx.search(n)]
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} entries of {EXPIRY_VARIABLE} match {principal!r}; pass --expiry-name {principal}=ENTRY (names: {names})")
    return hits[0]


def update_expiry_list(raw_json: str, name: str, expires: dt.date | None) -> str:
    """The variable's JSON with one entry's date replaced; other entries and any extra keys are kept in order."""
    data = json.loads(raw_json)
    for item in data:
        if item["name"] == name:
            item["expires"] = expires.isoformat() if expires else None
            return json.dumps(data)
    raise ValueError(f"no entry named {name!r} in {EXPIRY_VARIABLE}")


# ---- GitHub and Databricks adapters (thin; the tests replace them) -------------------------------------------------------------

class GitHub:
    def __init__(self, token: str, repo: str = REPO):
        self.token, self.repo = token, repo

    def _call(self, method: str, path: str, body=None):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "packsense-rotation"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            needs = e.headers.get("X-Accepted-GitHub-Permissions") if e.headers else None   # names the permission a 403 lacks; not a secret
            raise RuntimeError(f"GitHub {method} {path} -> HTTP {e.code}" + (f" (needs: {needs})" if needs else "")) from None   # never the body or the token

    def variable(self) -> str:
        return self._call("GET", f"/actions/variables/{EXPIRY_VARIABLE}")["value"]

    def set_variable(self, value: str) -> None:
        self._call("PATCH", f"/actions/variables/{EXPIRY_VARIABLE}", {"name": EXPIRY_VARIABLE, "value": value})

    def public_key(self, env: str) -> tuple[str, str]:
        d = self._call("GET", f"/environments/{env}/secrets/public-key")
        return d["key_id"], d["key"]

    def secret_updated_at(self, env: str, name: str):
        try:
            return self._call("GET", f"/environments/{env}/secrets/{name}")["updated_at"]
        except RuntimeError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def put_secret(self, env: str, name: str, value: str) -> None:
        key_id, key = self.public_key(env)
        self._call("PUT", f"/environments/{env}/secrets/{name}", {"encrypted_value": encrypt_for_github(key, value), "key_id": key_id})


class Databricks:
    def __init__(self, host: str, token: str):
        from databricks.sdk import WorkspaceClient
        self.host = host
        self.w = WorkspaceClient(host=host, token=token, auth_type="pat")

    def sp_id(self, client_id: str) -> str:
        found = [sp for sp in self.w.service_principals.list(filter=f'applicationId eq "{client_id}"')]
        if len(found) != 1:
            raise RuntimeError(f"expected one service principal for client id {client_id[:8]}..., found {len(found)}")
        return str(found[0].id)

    def list_secrets(self, sp_id: str) -> list:
        return [(s.id, s.expire_time) for s in self.w.service_principal_secrets_proxy.list(sp_id)]

    def create_secret(self, sp_id: str, lifetime: str) -> tuple:
        r = self.w.service_principal_secrets_proxy.create(sp_id, lifetime=lifetime)
        return r.id, r.secret, r.expire_time

    def delete_secret(self, sp_id: str, secret_id: str) -> None:
        self.w.service_principal_secrets_proxy.delete(sp_id, secret_id)

    def put_scope_secret(self, scope: str, value: str) -> None:
        self.w.secrets.put_secret(scope, SCOPE_KEY, string_value=value)

    def scope_has_secret(self, scope: str) -> bool:
        return SCOPE_KEY in {s.key for s in self.w.secrets.list_secrets(scope)}

    def verify(self, client_id: str, secret: str) -> bool:
        """True when the new secret signs in as that principal (an OAuth secret can take a few seconds to become valid)."""
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient(host=self.host, client_id=client_id, client_secret=secret, auth_type="oauth-m2m")
        return str(w.current_user.me().user_name).lower() == client_id.lower()


# ---- the rotation ------------------------------------------------------------------------------------------------------------

def rotate_one(name: str, dbx, gh, *, lifetime_days: int, keep_old: bool, expiry_override: str | None = None,
               emit=print, sleep=time.sleep) -> dict:
    cfg = PRINCIPALS[name]
    lifetime = lifetime_string(lifetime_days)
    sp = dbx.sp_id(cfg["client_id"])
    old = dbx.list_secrets(sp)
    if len(old) >= MAX_SECRETS - 1:
        raise RuntimeError(f"{name} already holds {len(old)} secrets; delete the surplus in Databricks first (the limit is {MAX_SECRETS})")
    entry = match_expiry_entry(json.loads(gh.variable()), name, expiry_override)   # fail BEFORE creating anything
    before = gh.secret_updated_at(cfg["github_env"], SECRET_NAME)
    emit(f"[{name}] {len(old)} existing secret(s); expiry entry {entry!r}; GitHub environment {cfg['github_env']}")

    secret_id, secret, expire_time = dbx.create_secret(sp, lifetime)
    expires = parse_expire_time(expire_time)
    emit(f"[{name}] 1 created secret {secret_id}, expires {expires}")
    try:
        for attempt in range(6):
            if dbx.verify(cfg["client_id"], secret):
                break
            sleep(5)
        else:
            raise RuntimeError("the new secret does not sign in as the principal")
        emit(f"[{name}] 2 the new secret signs in as the principal")
        if cfg["scope"]:
            dbx.put_scope_secret(cfg["scope"], secret)
            emit(f"[{name}] 3 stored in scope {cfg['scope']}")
        gh.put_secret(cfg["github_env"], SECRET_NAME, secret)
        after = gh.secret_updated_at(cfg["github_env"], SECRET_NAME)
        if after is None or after == before:
            raise RuntimeError(f"GitHub environment {cfg['github_env']}: the secret's updated_at did not change")
        emit(f"[{name}] 4 stored in GitHub environment {cfg['github_env']} (updated_at {after})")
    finally:
        secret = None   # never kept beyond this block
    gh.set_variable(update_expiry_list(gh.variable(), entry, expires))
    emit(f"[{name}] 5 {EXPIRY_VARIABLE}: {entry!r} now expires {expires}")
    if keep_old:
        emit(f"[{name}] 6 old secrets kept: {[i for i, _ in old]}")
    else:
        for old_id, _ in old:
            dbx.delete_secret(sp, old_id)
        emit(f"[{name}] 6 deleted old secret(s) {[i for i, _ in old]}")
    return {"principal": name, "new_secret_id": secret_id, "expires": expires.isoformat(), "deleted": [] if keep_old else [i for i, _ in old]}


def plan_one(name: str, dbx, gh, *, expiry_override: str | None = None, emit=print) -> None:
    """Everything `rotate` needs, checked without changing anything."""
    cfg = PRINCIPALS[name]
    sp = dbx.sp_id(cfg["client_id"])
    old = dbx.list_secrets(sp)
    entry = match_expiry_entry(json.loads(gh.variable()), name, expiry_override)
    gh.public_key(cfg["github_env"])
    scope = "n/a" if not cfg["scope"] else ("has " + SCOPE_KEY if dbx.scope_has_secret(cfg["scope"]) else "MISSING " + SCOPE_KEY)
    room = "ok" if len(old) < MAX_SECRETS - 1 else "TOO MANY"
    emit(f"[{name}] principal found; {len(old)} secret(s) ({room}); expiry entry {entry!r}; GitHub env {cfg['github_env']} reachable; scope {cfg['scope']}: {scope}")


# ---- command line ------------------------------------------------------------------------------------------------------------

def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def need(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing environment variable: {name}")
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["plan", "rotate", "show-expiry", "set-expiry"])
    ap.add_argument("args", nargs="*", help="set-expiry: NAME and YYYY-MM-DD or null")
    ap.add_argument("--env-file")
    ap.add_argument("--principal", action="append", choices=list(PRINCIPALS), default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--lifetime-days", type=int, default=DEFAULT_LIFETIME_DAYS)
    ap.add_argument("--keep-old", action="store_true")
    ap.add_argument("--expiry-name", action="append", default=[], metavar="PRINCIPAL=ENTRY")
    a = ap.parse_args(argv)
    if a.env_file:
        load_env_file(a.env_file)
    for stale in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(stale, None)
    gh = GitHub(need("GITHUB_ROTATION_TOKEN"))

    if a.command == "show-expiry":
        for e in json.loads(gh.variable()):
            print(f"{e['name']}: {e.get('expires')}")
        return 0
    if a.command == "set-expiry":
        if len(a.args) != 2:
            sys.exit("usage: set-expiry NAME YYYY-MM-DD|null")
        when = None if a.args[1] == "null" else dt.date.fromisoformat(a.args[1])
        gh.set_variable(update_expiry_list(gh.variable(), a.args[0], when))
        print(f"{a.args[0]}: {when}")
        return 0

    names = list(PRINCIPALS) if a.all else [n for n in PRINCIPALS if n in a.principal]
    if not names:
        sys.exit("choose --principal NAME (repeatable) or --all")
    overrides = dict(x.split("=", 1) for x in a.expiry_name)
    dbx = Databricks(need("DATABRICKS_HOST"), need("DATABRICKS_TOKEN"))
    for n in names:
        if a.command == "plan":
            plan_one(n, dbx, gh, expiry_override=overrides.get(n))
        else:
            rotate_one(n, dbx, gh, lifetime_days=a.lifetime_days, keep_old=a.keep_old, expiry_override=overrides.get(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
