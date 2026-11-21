# Design and sources

Research checked November 21, 2026. This is a small diagnostic for a specific workflow, not a claim that filesystem import analysis is new or that no competing tool exists.

## Intended use

A developer declares the ordered source and vendor directories that their build or CI expects. The tool explains which file or package portion that declaration selects at each component. An optional physical-root expectation turns unexpected shadowing into a failing check. Unlike an installed-artifact comparison, this works on ordinary source trees and explains candidate precedence.

There is a tradeoff: skipping target execution means dynamic package behavior cannot be known. A useful report must state its model instead of calling a located file importable. Candidate enumeration also means an inaccessible later root produces an incomplete result even if an earlier winner is visible.

## Source ledger

- [Python importlib documentation](https://docs.python.org/3/library/importlib.html), Python Software Foundation, official API documentation. Establishes that dotted `importlib.util.find_spec` imports the parent; describes default filesystem finder APIs and loader suffixes. High confidence for API behavior, not a promise about arbitrary custom importers.
- [Python import reference](https://docs.python.org/3/reference/import.html), Python Software Foundation, language reference. Supports the distinction between module cache, meta path, path hooks, parent `__path__`, and filesystem lookup. High confidence.
- [PEP 420](https://peps.python.org/pep-0420/), Python namespace-package specification. Supports ordered namespace accumulation and concrete-package precedence. High confidence for the intended algorithm; the tool still uses the interpreter's actual suffix lists.
- [CPython issue 92994](https://github.com/python/cpython/issues/92994), public issue discussion. Evidence that a supposedly execution-free dotted spec lookup can surprise developers by importing parent modules. It does not establish demand for this particular tool, usage, or adoption. Medium confidence as problem evidence.
- [Ruff A005](https://docs.astral.sh/ruff/rules/stdlib-module-shadowing/), Astral, rule documentation. An existing solution for standard-library module naming conflicts. Prefer it when that is the question. High confidence for documented rule scope.
- [deptry](https://github.com/osprey-oss/deptry/), project README. Checks missing, unused, and transitive dependencies by comparing imports with dependency declarations. It is not presented here as a general route debugger. High confidence for the documented core purpose, not an exhaustive feature audit.
- [Import Linter](https://import-linter.readthedocs.io/en/stable/), project documentation. Enforces architecture contracts between modules and offers architecture exploration. Prefer it for dependency direction and layering rules. High confidence for documented purpose.
- [Find a module path without importing](https://stackoverflow.com/questions/4693608/find-path-of-module-without-importing-in-python), community question and answers. Shows the recurring question and the important limitation that dynamic parent behavior prevents a universally correct execution-free answer. Community context, not a normative algorithm or proof of current product demand.

- [Detect Shadowed Modules README](https://github.com/iloveitaly/detect-shadowed-modules/blob/master/README.md), project documentation, read November21,2026. Closer existing diagnostic: duplicate immediate directory names across search roots, optional uv editable-path discovery, ownership hints, JSON and conflict exit codes. Source inspection at10598cbf8e45c9f5666e87b4f4336984f878e8cd confirmed `find_conflicts(paths=...)` accepts explicit roots and its helper filters to immediate subdirectories. Explicit roots and JSON are therefore not unique features of this project. The narrower contribution here is dotted-name route modeling for module/package/namespace selection and a physical expected-root gate. This is a scoped comparison, not an exhaustive audit of that project's current or future capabilities.

No external source code is copied into this project. The implementation is a bounded directory model, with the standard-library finder and actual harmless subprocess imports used as test oracles.

## Validation and limits

The tests cover a 25-pair two-root grid and 120 seeded nested layouts. The nested oracle starts isolated child processes that import only test-created harmless modules. Invalid extension and bytecode files are used only with spec lookup, never loaded. Additional checks cover no target source reads, no target writes, custom-hook avoidance, symlink expectations, errors, special files, and output handling.

The scan budget applies across a whole call, including later queries. A single look-ahead entry can exceed the stated count by one to detect exhaustion. Root and component counts bound the remaining loop structure. None of these bounds cancels a slow filesystem call. No concurrent-filesystem snapshot, security certification, or Windows/macOS parity is claimed.
