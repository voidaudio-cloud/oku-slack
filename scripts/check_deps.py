"""Dependency-parity guard: every third-party import under oku_slack/ must be declared in the manifest of its runtime.

Runtimes:
  bridge = oku_slack/*.py and oku_slack/world/*.py  -> requirements.txt (+ requirements-dev.txt)
  wheel  = oku_slack/wheel/**/*.py                   -> requirements-wheel.txt (+ requirements-dev.txt)

Parses source with ast only (never imports the scanned modules), stdlib only.
Usage: python3 scripts/check_deps.py   (from the repo root; exit 0 = all declared, 1 = undeclared, 2 = manifest missing)
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "oku_slack"
MANIFESTS = {
    "bridge": ["requirements.txt", "requirements-dev.txt"],
    "wheel": ["requirements-wheel.txt", "requirements-dev.txt"],
}
# import name -> distribution name (only where they differ)
IMPORT_TO_DIST = {"PIL": "pillow", "slack": "slack_bolt"}
STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def runtime_of(path):
    rel = path.relative_to(PKG)
    return "wheel" if rel.parts[0] == "wheel" else "bridge"


def _guarded_ids(tree):
    """ids of import nodes inside a try-body whose handler catches ImportError: optional, may be absent."""
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches = any(h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError"))
                      for h in node.handlers)
        if catches:
            for sub in node.body:
                for inner in ast.walk(sub):
                    guarded.add(id(inner))
    return guarded


def top_level_imports(source):
    """Yield (top_level_module_name, lineno, optional) for every absolute import in the source.
    optional=True marks an import guarded by try/except ImportError (the code runs without it)."""
    tree = ast.parse(source)
    guarded = _guarded_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno, id(node) in guarded
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module.split(".")[0], node.lineno, id(node) in guarded


def read_declared(names):
    declared = set()
    for name in names:
        path = ROOT / name
        if not path.exists():
            raise FileNotFoundError(name)
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if m:
                declared.add(norm(m.group(1)))
    return declared


def scan():
    """Return sorted list of (relpath, lineno, module, runtime, optional) for third-party imports."""
    found = []
    for path in sorted(PKG.rglob("*.py")):
        runtime = runtime_of(path)
        for mod, lineno, optional in top_level_imports(path.read_text(encoding="utf-8")):
            if mod in STDLIB or mod == "oku_slack":
                continue
            found.append((path.relative_to(ROOT).as_posix(), lineno, mod, runtime, optional))
    return found


def check(found):
    """Return list of human-readable problems for imports not declared in their runtime's manifests."""
    cache = {}
    problems = []
    for relpath, lineno, mod, runtime, optional in found:
        if optional:  # guarded by ImportError: the code path works without it, so it need not be declared
            continue
        if runtime not in cache:
            cache[runtime] = read_declared(MANIFESTS[runtime])
        dist = norm(IMPORT_TO_DIST.get(mod, mod))
        if dist not in cache[runtime]:
            problems.append(
                f"{relpath}:{lineno}: '{mod}' is imported by the {runtime} runtime "
                f"but '{IMPORT_TO_DIST.get(mod, mod)}' is not declared in {' / '.join(MANIFESTS[runtime])}"
            )
    return problems


def main():
    try:
        found = scan()
        problems = check(found)
    except FileNotFoundError as e:
        print(f"check_deps: manifest missing: {e}", file=sys.stderr)
        return 2
    if problems:
        print("check_deps: undeclared third-party dependencies:")
        for p in problems:
            print("  " + p)
        return 1
    print(f"check_deps: ok ({len(found)} third-party imports declared across bridge and wheel runtimes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
