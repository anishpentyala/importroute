# importroute

[![Tests](https://github.com/anishpentyala/importroute/actions/workflows/tests.yml/badge.svg)](https://github.com/anishpentyala/importroute/actions)

Explain where a Python name would be found in an explicit, ordered set of directories, without importing the target package.

## Quickstart

```sh
python -m pip install importroute==0.1.0
mkdir -p demo/checkout demo/site
printf 'raise RuntimeError("do not import this")\n' > demo/checkout/widget.py
printf 'pass\n' > demo/site/widget.py
importroute widget --path demo/checkout --path demo/site --expect-under demo/site --json
```

This exits 1 with top-level `FAILED` and per-module `EXPECTATION_FAILED`: the first root selects the checkout's
`widget.py`, outside the expected site directory. The exception in that file
does not run. Reverse the two `--path` arguments and this example passes.
This models declared filesystem roots, not custom import hooks or a live
process's full import behavior.

Install the pinned 0.1.0 release from [PyPI](https://pypi.org/project/importroute/0.1.0/):

```sh
python -m pip install importroute==0.1.0
```

The package release is pinned separately from later repository development.
Source-install commands in this README use the checked-out code, which may be newer.

A checkout can hide an installed dependency. A regular package in a later root can replace earlier namespace portions. A package can also win over a same-name module at one root. `importroute` shows the candidates and the route through each dotted-name component, and can fail a CI check when that route leaves an expected directory.

This is a bounded filesystem model, **not proof of what a running process imports**. It does not evaluate initializers, custom finders, editable-install hooks, `.pth` files, archives, the module cache, or a package's dynamic `__path__` changes. It does not prove that selected code can load or is safe.

## Install

Python 3.10 or newer. No runtime dependencies.

```sh
python -m pip install .
importroute --help
```

Run the tool with the interpreter whose default extension suffixes you want to model. The pinned PyPI release and installation from this checkout are separate options; the checkout may contain newer changes.

## A reproducible shadowing check

```sh
mkdir -p demo/checkout demo/site
printf 'raise RuntimeError("do not import this")\n' > demo/checkout/widget.py
printf 'pass\n' > demo/site/widget.py

importroute widget --path demo/checkout --path demo/site
```

The report selects `demo/checkout/widget.py` and lists `demo/site/widget.py` as a later-root candidate. Paths are displayed as absolute paths. The first file's exception does not run.

Require the selected route to stay under the intended directory:

```sh
importroute widget --path demo/checkout --path demo/site \
  --expect-under demo/site --json
```

This exits 1 with top-level `FAILED` and per-module `EXPECTATION_FAILED`, because the first directory wins. Reversing the two `--path` arguments makes this example pass.

For a dotted name:

```sh
importroute acme.plugins.reader --path ./src --path ./vendor --json
```

Each component has its own `search_roots`, `candidates`, `selection`, `ignored_roots`, and `errors`. Child lookup follows the selected package directories, not the original top-level roots. Regular packages are assumed to retain their default directory `__path__`.

## Python API

```python
from importroute import trace_imports

report = trace_imports(
    ["widget", "acme.plugins.reader"],
    ["./src", "./vendor"],
    expected_root="./src",
)
print(report["status"])
```

Inputs must be iterables, not one string. Module names are absolute dotted identifiers. Relative names and path/glob patterns are rejected. Paths are literal: no environment-variable or tilde expansion. An empty path means the current directory. The function does not change `sys.path`.

## Selection rules

The model uses exact-case directory entries and the running interpreter's default extension, source, then legacy-bytecode suffix order.

- Within one root, a regular package beats a same-name module, including extension modules. Among matching files, default loader suffix order applies.
- Across roots, the first concrete module or regular package wins.
- Namespace portions combine in root order only if there is no concrete match. A later concrete match discards earlier namespace portions.
- A plain module cannot have a child. A selected regular package's missing child does not fall back to unrelated top-level roots.
- `__pycache__` entries without source are not treated as legacy same-directory `.pyc` candidates. Extension and bytecode files are located, never loaded or validated.

`--expect-under` checks the physical path of **every selected component**, including every namespace portion. A symlink pointing outside fails even when its lexical path is inside. The expected root must be an existing directory. This is a location check, not a trust or containment sandbox.

## Reports and exit codes

JSON reports use `format: "importroute/v1"`. All queries are retained. The overall status gives `INCOMPLETE` priority over failures.

| Exit | Meaning |
| --- | --- |
| 0 | Every query is `LOCATED`, with any expectation satisfied |
| 1 | A query is `MISSING`, `PARENT_NOT_PACKAGE`, or `EXPECTATION_FAILED` |
| 2 | Invalid input, command usage, or output failure |
| 3 | At least one query is `INCOMPLETE` |

An `INCOMPLETE` step may include a tentative selection from readable roots. Do not treat it as a passing result. Unreadable directories, non-directory roots such as archives, scan-budget exhaustion, and failed physical-path checks are explicit failures to complete the model. Missing roots are listed and ignored. Even an unsupported root after an apparent winner causes `INCOMPLETE`, because this tool promises a candidate inventory, not only a winner.

Top-level names with builtin or frozen precedence in this interpreter return `INCOMPLETE` instead of pretending a directory candidate is the runtime winner. Other non-filesystem behavior is excluded by the stated assumptions, not detected automatically.

Limits per call: 128 queries, 64 initial roots, 32 components per query, and 100,000 directory entries. One additional entry may be observed to detect that the entry budget was exceeded. Directory-name caches live only for the call. These are work limits, not a timeout: a slow filesystem or network mount can still block an operating-system call.

## When to use something else

For the spec selected by the real import system, use `importlib.util.find_spec`. Looking up a dotted name there can execute its parent package. If runtime behavior matters, reproduce the real process and inspect the actual imported module instead of relying on this model.

Ruff's `A005` checks standard-library name shadowing. deptry checks dependency declarations and imports. Import Linter checks architecture contracts. Those solve different problems; this tool does not replace them. Its narrower task is an explicit-directory route explanation with all candidates and an expected-root gate.

[Detect Shadowed Modules](https://github.com/iloveitaly/detect-shadowed-modules/blob/master/README.md) is a closer alternative for duplicate-directory checks across an environment's search paths. Its CLI includes uv editable locations and installed-distribution ownership; its Python API also accepts explicit roots. Prefer it for that environment-wide inventory. `importroute` instead follows requested dotted names, includes ordinary module files and loader suffix precedence, distinguishes namespace accumulation from concrete-package selection, and checks the physical path of every selected component against an expected root.

Do not run Python itself on a hostile checkout merely because this tool does not import target packages. Interpreter startup, the installed tool, and its own imports remain part of your execution environment. Use a trusted installation and working directory. Filesystem observations can race with concurrent changes and are not an atomic snapshot. The model intentionally does not follow platform case-folding or `PYTHONCASEOK` behavior.

## Development

```sh
python -m unittest discover -s tests -v
```

Tests compare 25 two-root layout pairs with the standard-library finder and 120 seeded nested layouts with actual harmless imports in isolated child processes. They also cover namespace precedence, suffix selection, symlinks, scan limits, no target execution, and output failures. This is Linux validation, not a claim of complete cross-platform import emulation.

See [design and sources](docs/design.md) for the scope and evidence.

MIT licensed.
