"""Publish the current site/ folder to the gh-pages branch (GitHub Pages serves that branch).

Usage (from the repo root, after the pipeline has rebuilt site/):  python scripts/publish_site.py
Only site/ is published. Nothing is committed to the branch you are on, and no branch is checked out.
"""
import os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def git(*args, env=None, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


html = (SITE / "index.html").read_text(encoding="utf-8")
as_of = re.search(r'"asOf":"([0-9-]+)"', html)
if not as_of:
    sys.exit("site/index.html has no prices date. Rebuild it with python pipeline/build.py first.")

with tempfile.TemporaryDirectory() as tmp:
    # A separate index, so the files staged on your branch are not touched.
    env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
    git(f"--work-tree={SITE}", "add", "--all", "--force", ".", env=env, cwd=SITE)
    tree = git("write-tree", env=env)

subprocess.run(["git", "fetch", "origin", "gh-pages"], cwd=ROOT, capture_output=True)  # fails only on the first publish
parent = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "origin/gh-pages"], cwd=ROOT,
                        capture_output=True, text=True).stdout.strip()
if parent and git("rev-parse", f"{parent}^{{tree}}") == tree:
    sys.exit(f"gh-pages already has this site (prices updated {as_of.group(1)}). Nothing to publish.")
commit = git("commit-tree", tree, *(["-p", parent] if parent else []),
             "-m", f"Publish site, prices updated {as_of.group(1)}")
git("push", "origin", f"{commit}:refs/heads/gh-pages")
print(f"Published {commit[:7]} (prices updated {as_of.group(1)}) to gh-pages.")
