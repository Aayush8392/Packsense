r"""Create a Label Studio project for a set of cards and import its tasks (local Label Studio on D:, port 8081). Prints counts only; the login comes from the .env next to the compose file.

  .venv\Scripts\python.exe p7_triage_ml\labelling\create_project.py --title "PackSense gate: practice 1" --tasks D:\...\packsense_gate\practice_1.json --env D:\...\label_studio\.env
  --shuffle-seed N   write the tasks in a new fixed order (round 2 of the real test)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cards_lib as cl  # noqa: E402

BASE = "http://127.0.0.1:8081"


def login(env_path: str) -> tuple[requests.Session, dict]:
    env = dict(line.strip().split("=", 1) for line in open(env_path, encoding="utf-8") if "=" in line)
    s = requests.Session()
    for _ in range(60):
        try:
            if requests.get(BASE + "/health", timeout=5).status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(5)
    else:
        sys.exit("Label Studio did not become healthy: start it first (docker compose up -d in the label_studio folder)")
    s.get(BASE + "/user/login", timeout=30)
    token = s.cookies.get("csrftoken")
    r = s.post(BASE + "/user/login", data={"email": env["LABEL_STUDIO_USERNAME"], "password": env["LABEL_STUDIO_PASSWORD"], "csrfmiddlewaretoken": token},
               headers={"Referer": BASE + "/user/login"}, timeout=30, allow_redirects=False)
    if r.status_code not in (200, 302):
        sys.exit(f"login failed ({r.status_code})")
    return s, {"X-CSRFToken": s.cookies.get("csrftoken") or token, "Referer": BASE + "/"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--env", required=True)
    ap.add_argument("--shuffle-seed", type=int)
    ap.add_argument("--discard-labels", action="store_true", help="with --replace: delete the project even if it holds labels (practice projects only)")
    ap.add_argument("--replace", action="store_true", help="delete a project with the same title first (practice projects only: its labels are lost)")
    args = ap.parse_args()
    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    if args.shuffle_seed is not None:
        random.Random(args.shuffle_seed).shuffle(tasks)
    for t in tasks:
        t["data"].update(cl.card_lines(t["data"]))
        t["data"].update(cl.glossary_lines(t["data"]))
    s, h = login(args.env)
    config = (HERE / "project_config.xml").read_text(encoding="utf-8")
    existing = [p for p in s.get(BASE + "/api/projects", headers=h, timeout=30).json().get("results", []) if p["title"] == args.title]
    if existing and args.replace:
        done = existing[0].get("total_annotations") or existing[0].get("num_tasks_with_annotations") or 0
        if done and not args.discard_labels:
            sys.exit(f"'{args.title}' already holds {done} labels: not deleted. Export them or delete the project yourself in Label Studio")
        s.delete(f"{BASE}/api/projects/{existing[0]['id']}", headers=h, timeout=60).raise_for_status()
        existing = []
    if existing:
        sys.exit(f"a project called '{args.title}' already exists (id {existing[0]['id']}); delete it in Label Studio first")
    r = s.post(BASE + "/api/projects", headers=h, json={"title": args.title, "label_config": config}, timeout=30)
    r.raise_for_status()
    pid = r.json()["id"]
    n = s.post(f"{BASE}/api/projects/{pid}/import", headers=h, json=tasks, timeout=120)
    print(f"project {pid} '{args.title}': import status {n.status_code}, {len(tasks)} tasks sent")


if __name__ == "__main__":
    main()
