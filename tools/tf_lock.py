"""Writes `.terraform.lock.hcl` for each Terraform root without Terraform (there is none on the laptop), from the public provider registry.

  python tools/tf_lock.py            write the lock files for the providers and constraints in infra/terraform/*/versions.tf
  python tools/tf_lock.py --check    exit 1 if a committed lock names a different version or lacks a hash the registry publishes

What Terraform writes and checks, reproduced here: for each platform it downloads the provider zip, takes `zh:<sha256 of the zip>` (which must equal the registry's
published checksum) and `h1:<base64 sha256 of the lines "<sha256 of each file>  <name>\\n" in name order>` (Terraform's "dirhash" of the zip's files). The newest version
inside the constraint is chosen. Run `terraform init -lockfile=readonly` (the workflows do) to see that Terraform accepts the result.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = [("linux", "amd64"), ("windows", "amd64"), ("darwin", "amd64"), ("darwin", "arm64")]
REGISTRY = "https://registry.terraform.io/v1/providers"


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "packsense-tf-lock"}), timeout=120) as r:
        return r.read()


def providers_of(root: Path) -> list[tuple[str, str, str]]:
    """(namespace, type, constraint) for each required provider of a root."""
    text = (root / "versions.tf").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'(\w+)\s*=\s*\{\s*source\s*=\s*"([\w-]+)/([\w-]+)"\s*version\s*=\s*"([^"]+)"', text):
        out.append((m.group(2), m.group(3), m.group(4)))
    return out


def newest_within(versions: list[str], constraint: str) -> str:
    m = re.fullmatch(r"~>\s*(\d+)\.(\d+)(?:\.(\d+))?", constraint)
    if not m:
        raise SystemExit(f"constraint {constraint!r} is not of the form ~> X.Y[.Z]")
    major, minor, patch = int(m.group(1)), int(m.group(2)), m.group(3)
    ok = []
    for v in versions:
        p = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v)           # no pre-releases
        if not p:
            continue
        t = tuple(int(x) for x in p.groups())
        if patch is None:
            good = t[0] == major and t[1] >= minor              # ~> 0.14 means >= 0.14.0, < 1.0.0
        else:
            good = t[0] == major and t[1] == minor and t[2] >= int(patch)
        if good:
            ok.append(t)
    if not ok:
        raise SystemExit(f"no version of the provider satisfies {constraint}")
    return ".".join(map(str, max(ok)))


def h1_of_zip(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    lines = "".join(f"{hashlib.sha256(z.read(n)).hexdigest()}  {n}\n" for n in sorted(i.filename for i in z.infolist() if not i.is_dir()))
    return "h1:" + base64.b64encode(hashlib.sha256(lines.encode()).digest()).decode()


def block(ns: str, typ: str, constraint: str) -> str:
    versions = [v["version"] for v in json.loads(get(f"{REGISTRY}/{ns}/{typ}/versions"))["versions"]]
    version = newest_within(versions, constraint)
    hashes = []
    for os_, arch in PLATFORMS:
        meta = json.loads(get(f"{REGISTRY}/{ns}/{typ}/{version}/download/{os_}/{arch}"))
        data = get(meta["download_url"])
        zh = hashlib.sha256(data).hexdigest()
        if zh != meta["shasum"]:
            raise SystemExit(f"{ns}/{typ} {version} {os_}_{arch}: downloaded zip does not match the registry checksum")
        hashes += [h1_of_zip(data), "zh:" + zh]
    body = "".join(f'    "{h}",\n' for h in sorted(set(hashes)))
    return (f'provider "registry.terraform.io/{ns.lower()}/{typ}" {{\n  version     = "{version}"\n  constraints = "{constraint}"\n  hashes = [\n{body}  ]\n}}\n')


def lock_text(root: Path) -> str:
    header = "# This file is maintained automatically by \"terraform init\".\n# Manual edits may be lost in future updates.\n\n"
    return header + "\n".join(block(*p) for p in sorted(providers_of(root), key=lambda p: (p[0].lower(), p[1])))


def main(argv: list[str]) -> int:
    check = "--check" in argv
    bad = 0
    for root in sorted((ROOT / "infra" / "terraform").glob("*/versions.tf")):
        d = root.parent
        text = lock_text(d)
        target = d / ".terraform.lock.hcl"
        if check:
            same = target.exists() and target.read_text(encoding="utf-8").replace("\r\n", "\n") == text
            print(d.name, "ok" if same else "DIFFERS")
            bad += 0 if same else 1
        else:
            target.write_text(text, encoding="utf-8", newline="\n")
            print("wrote", target.relative_to(ROOT))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
