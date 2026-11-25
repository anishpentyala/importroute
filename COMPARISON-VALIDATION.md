# Ordered path-plan comparison validation, November 24, 2026

Base public main fba87ba5d09184f921ee4724c5d452af1e9a7dc4. API compare_routes and
CLI repeated --compare-path compare terminal status and every component's
selection. Includes ordered/repeated namespace portions; ignores root positions,
discarded candidates and scan counts. Both full traces retained. Incomplete
dominates changed. Matching missing or failed expectations can be unchanged.
No target imports/source reads, runtime/loadability/code-byte/history certificate.
Both plans observed now sequentially; independent scan budgets, filesystem races
and slow calls remain. Default trace mode/report unchanged, no release/version
change. Existing output delivery behavior reused, not widened in this feature.

Actual Python 3.10.12, 3.13.18 and 3.15.2: all 53 unittest tests pass. Neutral
built-wheel installed in fresh Python 3.15 environment from /tmp: all 53 pass.
Original 39 tests retained. Fourteen new tests include a 25-layout-pair native
PathFinder oracle, 6 ordered/duplicate-root plans on each side, top-level and
child names = 1,800 comparisons. PathFinder locates harmless test fixtures only,
no initializer executed. Tests cover selected origin, namespace order/duplicates,
shadowed-only deltas, missing, nonpackage parent, incomplete/builtin precedence,
scan-limit independence, generator modules, immutability, invalid inputs,
expectation failure, symlink lexical origins, CLI human/JSON 0/1/2/3 and short
output failures. Original suite still includes 120 isolated actual harmless
imports and no-target-execution checks.

Four mutants killed: ignore selected origins (5 failures), ignore namespace
order (2), ignore incomplete state (3), terminal-only comparison (2). Source
restored; final 53 pass. Ruff check passes after initial import/unused-import and
single-line-if findings corrected. Initial tests passed before style fixes.
Sdist/wheel build succeeded with the existing project's license-table deprecation
warning, unchanged. No test or requirement weakened.

Primary semantics re-read November 24:
https://docs.python.org/3/library/importlib.html
https://peps.python.org/pep-0420/
Both support the inherited bounded filesystem/ordered namespace model, not
arbitrary hooks or dynamic __path__ behavior. No external implementation copied.

Review focus: whether selected-route equality is useful and accurately bounded,
namespace order and intermediate-component evidence, incomplete dominance,
CLI comparison exit meaning versus embedded expectation failure, independent
scan budgets and default compatibility. No public action before PASS.
