#!/usr/bin/env python3
"""Pin every container base image to an immutable digest (audit W17).

A tag such as `postgres:16-alpine` can change under us between two deploys; `postgres:16-alpine@sha256:<digest>` cannot.
This script finds every image reference the repo builds or runs and rewrites it to `name:tag@sha256:...`:

  * `image:` entries of docker-compose*.yml
  * `FROM` lines of apps/*/Dockerfile (stage aliases, `scratch` and ARG-driven references are skipped)

    scripts/pin_images.py            # list references and whether they are pinned
    scripts/pin_images.py --check    # exit 1 when anything is not pinned (CI after the first pin)
    scripts/pin_images.py --pin      # resolve and write digests for unpinned references
    scripts/pin_images.py --pin --refresh   # also move already pinned references to the tag's current digest

Resolving a digest needs access to the registries, so it runs where Docker Hub is reachable: the `Pin images` workflow
(.github/workflows/pin-images.yml) does it on a GitHub runner and opens a pull request. Dependabot (docker /
docker-compose ecosystems) then keeps the pins fresh. Nothing here invents a digest: an unresolvable reference is an error.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
COMPOSE_IMAGE = re.compile(r"^(?P<lead>\s*image:\s*)(?P<ref>[^\s#]+)(?P<tail>.*)$")
DOCKER_FROM = re.compile(r"^(?P<lead>FROM\s+(?:--platform=\S+\s+)?)(?P<ref>\S+)(?P<tail>(?:\s+AS\s+\S+)?\s*)$", re.IGNORECASE)


class Ref(NamedTuple):
    file: Path
    line: int  # 1-based
    ref: str

    @property
    def pinned(self) -> bool:
        return bool(DIGEST.search(self.ref))

    @property
    def tagged_name(self) -> str:
        """`name:tag` without the digest: what a registry is asked to resolve."""
        return DIGEST.sub("", self.ref)


def pin_files(root: Path = ROOT) -> list[Path]:
    return sorted([*root.glob("docker-compose*.yml"), *root.glob("apps/*/Dockerfile")])


def find_refs(root: Path = ROOT) -> list[Ref]:
    refs: list[Ref] = []
    for path in pin_files(root):
        stages: set[str] = set()
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if path.name == "Dockerfile":
                m = DOCKER_FROM.match(line)
                if not m:
                    continue
                ref = m.group("ref")
                alias = re.search(r"\s+AS\s+(\S+)", m.group("tail"), re.IGNORECASE)
                is_stage_ref = ref in stages
                if alias:
                    stages.add(alias.group(1))
                if is_stage_ref or ref.lower() == "scratch" or "$" in ref:
                    continue
            else:
                m = COMPOSE_IMAGE.match(line)
                if not m or "$" in m.group("ref"):
                    continue
                ref = m.group("ref")
            refs.append(Ref(path, number, ref))
    return refs


def resolve_digest(tagged_name: str) -> str:
    """Ask the registry for the manifest-list digest of `name:tag` (works for single- and multi-arch images)."""
    out = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", tagged_name, "--format", "{{.Manifest.Digest}}"],
        capture_output=True,
        text=True,
    )
    digest = out.stdout.strip()
    if out.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError(f"cannot resolve {tagged_name}: {(out.stderr or out.stdout).strip()[:200]}")
    return digest


def rewrite(root: Path, refs: list[Ref], digests: dict[str, str], refresh: bool) -> int:
    """Write `name:tag@digest` for every reference whose tagged name has a digest. Returns the number of lines changed."""
    changed = 0
    by_file: dict[Path, list[Ref]] = {}
    for r in refs:
        by_file.setdefault(r.file, []).append(r)
    for path, items in by_file.items():
        lines = path.read_text().splitlines(keepends=True)
        for r in items:
            if r.pinned and not refresh:
                continue
            digest = digests.get(r.tagged_name)
            if not digest:
                continue
            new = f"{r.tagged_name}@{digest}"
            if r.ref == new:
                continue
            original = lines[r.line - 1]
            lines[r.line - 1] = original.replace(r.ref, new, 1)
            changed += 1
        path.write_text("".join(lines))
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 when any reference is not pinned by digest")
    parser.add_argument("--pin", action="store_true", help="resolve and write digests")
    parser.add_argument("--refresh", action="store_true", help="with --pin: also re-resolve already pinned references")
    args = parser.parse_args(argv)

    refs = find_refs()
    if not refs:
        print("no image references found", file=sys.stderr)
        return 1
    if args.pin:
        digests: dict[str, str] = {}
        try:
            for name in sorted({r.tagged_name for r in refs if args.refresh or not r.pinned}):
                digests[name] = resolve_digest(name)
                print(f"{name} -> {digests[name]}")
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"updated {rewrite(ROOT, refs, digests, args.refresh)} reference(s)")
        refs = find_refs()
    unpinned = [r for r in refs if not r.pinned]
    for r in refs:
        print(f"{'pinned  ' if r.pinned else 'UNPINNED'} {r.file.relative_to(ROOT)}:{r.line}  {r.ref}")
    if args.check and unpinned:
        print(f"{len(unpinned)} image reference(s) are not pinned by digest (run the 'Pin images' workflow)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
