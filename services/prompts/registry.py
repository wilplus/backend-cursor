"""Prompt registry — discovery, hashing, and the drift lockfile.

Every module in ``services/prompts/`` that declares ``REGISTER`` is a
prompt module. This registry imports them all, hashes every entry, and
compares against the checked-in ``prompts.lock.json``:

  * static prompt (str)      → sha256 of the UTF-8 text
  * builder prompt (callable) → sha256 of the function's source code
                                (``inspect.getsource``), so editing the
                                interpolation logic counts as a prompt
                                edit too — templates drift through their
                                glue as often as through their text.

CLI (used by CI and by developers):

    python -m services.prompts.registry check
        exit 0 when the lockfile matches reality, exit 1 with a list of
        added / removed / changed prompt ids otherwise.

    python -m services.prompts.registry update
        rewrite prompts.lock.json from the current code. Run this after
        any intentional prompt edit and commit the diff — the lockfile
        diff IS the prompt-change review artifact.

    python -m services.prompts.registry changed --against <old-lock.json>
        print the prompt ids whose hash differs from an older lockfile
        (one per line). CI uses this against the merge-base lockfile to
        decide which golden evals must run.

No LLM calls, no network, no db — safe to run anywhere, including the
credential-less CI unit tier.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import pkgutil
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

_PACKAGE = "services.prompts"
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent.parent
LOCKFILE_PATH = _PACKAGE_DIR / "prompts.lock.json"


@dataclass(frozen=True)
class SourceRef:
    """A prompt that still lives INLINE in its module (pending physical
    extraction) but is drift-tracked here by hashing its source segment.

    ``path`` is repo-relative; ``symbol`` is a module-level constant /
    function name, or ``"Class.method"``. ``symbol=None`` hashes the
    whole file (for prompt files like the community-content strategy
    .md, or files whose prompt text is diffuse, like llm_schemas).

    Resolution is pure ``ast`` over the file text — no import, no env,
    no side effects — so the drift gate covers modules (openai_service,
    v2_routes, life_engine…) that cannot be imported in a
    credential-less CI tier. Renaming or deleting the symbol fails the
    manifest loudly, so a refactor can't silently drop coverage.
    """
    path: str
    symbol: Optional[str] = None


PromptEntry = Union[str, Callable[..., str], SourceRef]


def _hash_source_ref(ref: SourceRef) -> str:
    file_path = _REPO_ROOT / ref.path
    source = file_path.read_text(encoding="utf-8")
    if ref.symbol is None:
        return _hash_text(source)
    import ast as _ast
    tree = _ast.parse(source)
    class_name, _, member = ref.symbol.partition(".")
    want_name = member or class_name
    scope = tree.body
    if member:
        for node in tree.body:
            if isinstance(node, _ast.ClassDef) and node.name == class_name:
                scope = node.body
                break
        else:
            raise ValueError(f"{ref.path}: class {class_name!r} not found")
    segments: list[str] = []
    for node in scope:
        found = False
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            found = node.name == want_name
        elif isinstance(node, _ast.Assign):
            found = any(
                isinstance(t, _ast.Name) and t.id == want_name
                for t in node.targets
            )
        elif isinstance(node, _ast.AnnAssign):
            found = (isinstance(node.target, _ast.Name)
                     and node.target.id == want_name)
        if found:
            seg = _ast.get_source_segment(source, node)
            if seg:
                segments.append(seg)
    if not segments:
        raise ValueError(
            f"{ref.path}: symbol {ref.symbol!r} not found — if it moved "
            "or was extracted, update services/prompts/pending.py"
        )
    return _hash_text("\n".join(segments))

# Prompt ids are "<surface>.<part>", e.g. "say_it_stronger.system".
# The surface half matches the ``surface=`` string the service passes to
# chat_complete wherever one exists, so llm.chat log lines, llm_usage
# cost rows, and eval datasets all key on the same name.
_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

# Modules in the package that are infrastructure, not prompt modules.
_EXCLUDED_MODULES = {"registry", "__init__"}


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_builder(fn: Callable[..., str]) -> str:
    # dedent so the hash doesn't change if a builder is ever moved
    # between indentation levels without its logic changing.
    source = textwrap.dedent(inspect.getsource(fn))
    return _hash_text(source)


def iter_prompt_modules():
    """Yield (module_name, module) for every prompt module in the package."""
    for info in pkgutil.iter_modules([str(_PACKAGE_DIR)]):
        if info.name in _EXCLUDED_MODULES or info.ispkg:
            continue
        module = importlib.import_module(f"{_PACKAGE}.{info.name}")
        if hasattr(module, "REGISTER"):
            yield info.name, module


def manifest() -> dict[str, dict[str, Any]]:
    """The current on-disk truth: {prompt_id: {sha256, kind, module}}.

    Raises ValueError on malformed ids, duplicate ids across modules,
    empty static prompts, or unsupported entry types — a broken
    declaration should fail loudly, not hash quietly.
    """
    out: dict[str, dict[str, Any]] = {}
    for mod_name, module in iter_prompt_modules():
        register = getattr(module, "REGISTER")
        if not isinstance(register, dict):
            raise ValueError(
                f"{_PACKAGE}.{mod_name}.REGISTER must be a dict, "
                f"got {type(register).__name__}"
            )
        for prompt_id, entry in register.items():
            if not _ID_RE.match(prompt_id or ""):
                raise ValueError(
                    f"{_PACKAGE}.{mod_name}: bad prompt id {prompt_id!r} "
                    "(want '<surface>.<part>', lowercase snake)"
                )
            if prompt_id in out:
                raise ValueError(
                    f"duplicate prompt id {prompt_id!r} "
                    f"({out[prompt_id]['module']} vs {mod_name})"
                )
            if isinstance(entry, str):
                if not entry.strip():
                    raise ValueError(
                        f"{_PACKAGE}.{mod_name}: static prompt "
                        f"{prompt_id!r} is empty"
                    )
                digest, kind = _hash_text(entry), "static"
            # Name-based check, not isinstance: running the CLI via
            # ``python -m`` loads this file as __main__, so pending.py's
            # SourceRef import is a different class object.
            elif type(entry).__name__ == "SourceRef" and hasattr(entry, "path"):
                digest, kind = _hash_source_ref(entry), "source_ref"
            elif callable(entry):
                digest, kind = _hash_builder(entry), "builder"
            else:
                raise ValueError(
                    f"{_PACKAGE}.{mod_name}: {prompt_id!r} must be a "
                    f"str or callable, got {type(entry).__name__}"
                )
            out[prompt_id] = {
                "sha256": digest,
                "kind": kind,
                "module": mod_name,
            }
    return dict(sorted(out.items()))


def read_lockfile(path: Path = LOCKFILE_PATH) -> dict[str, dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("prompts", {})


def write_lockfile(path: Path = LOCKFILE_PATH) -> dict[str, dict[str, Any]]:
    prompts = manifest()
    payload = {
        "_comment": (
            "Generated by `python -m services.prompts.registry update`. "
            "Do not edit by hand. A diff in this file IS a prompt change "
            "— CI runs the matching golden evals for every changed id."
        ),
        "prompts": prompts,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return prompts


def diff_against(old: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Compare the current manifest to an older lockfile's prompts dict."""
    current = manifest()
    added = sorted(set(current) - set(old))
    removed = sorted(set(old) - set(current))
    changed = sorted(
        pid for pid in set(current) & set(old)
        if current[pid]["sha256"] != old[pid]["sha256"]
    )
    return {"added": added, "removed": removed, "changed": changed}


def check() -> tuple[bool, dict[str, list[str]]]:
    """True when the lockfile matches the code, plus the delta if not."""
    if not LOCKFILE_PATH.exists():
        return False, {"added": sorted(manifest()), "removed": [],
                       "changed": []}
    delta = diff_against(read_lockfile())
    ok = not (delta["added"] or delta["removed"] or delta["changed"])
    return ok, delta


def _main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("check", "update", "changed"):
        print(__doc__)
        return 2

    cmd = argv[0]
    if cmd == "update":
        prompts = write_lockfile()
        print(f"prompts.lock.json updated — {len(prompts)} prompts.")
        return 0

    if cmd == "check":
        ok, delta = check()
        if ok:
            print(f"prompt registry OK — {len(manifest())} prompts match "
                  "prompts.lock.json.")
            return 0
        for label in ("added", "removed", "changed"):
            for pid in delta[label]:
                print(f"{label}: {pid}")
        print(
            "\nprompts.lock.json is stale. If this prompt change is "
            "intentional, run:\n    python -m services.prompts.registry "
            "update\nand commit the lockfile diff."
        )
        return 1

    # changed --against <old-lock.json>
    if len(argv) != 3 or argv[1] != "--against":
        print("usage: python -m services.prompts.registry changed "
              "--against <old-lock.json>")
        return 2
    old_path = Path(argv[2])
    old = read_lockfile(old_path) if old_path.exists() else {}
    delta = diff_against(old)
    for pid in delta["added"] + delta["changed"]:
        print(pid)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
