# Complete CLI delivery validation, November 24, 2026

Base main 222a046d0fdf266b9b6184cfbab4ee3cbaca6158. Local reproduction:
python -m importroute --help with stdout=/dev/full returns120 before fix;
missing arguments with stderr=/dev/full returns120 before fix. The source
report path checks writes, but argparse writes bypassed it and parser SystemExit
bypassed process shutdown handling. No filesystem-model change is needed.

Fix shares a checked text writer between reports and parser diagnostics,
checking integer write result, full count and flush. Parser output failures
return2. Normal embedded parser SystemExit preserved. Process entrypoint catches
parser exits and checks stdout/stderr flush, detaching only failed streams in
its own process shutdown scope. main(argv) leaves caller streams unchanged.
Unexpected trace AttributeError still propagates, not swallowed as output error.

59 unittest tests PASS on actual Python3.10.12,3.13.18,3.15.2; original53 retained.
Six new test methods include30 parser stream/destination subcases,12 short/invalid
report write cases,6 real module invocations with full device/closed pipe,
6 late-flush/normal-SystemExit runner cases, unexpected defect propagation,
and3 normal help/usage cases. New regression file against original main gives
8 failures19 errors. Four independent mutants killed: parser bypass7 errors,
short-write bypass6 failures3 errors,flush bypass12 failures3 errors,
shutdown-code bypass4 failures. Source restored; final59PASS and RuffPASS after
one new-test import sort correction. No test or requirement weakened.

Sdist and wheel buildPASS with inherited license-table deprecation warning.
Fresh isolated Python3.15 environment installs the built wheel, then runs all59
tests from /tmp successfully. No PyPI publication, tag or dependency change.
No network lookup or target import added. Existing route oracle tests retained.

Review focus: parser destination semantics when stdout/stderr is None; preservation
of embedded SystemExit and stream ownership; exit2 for failed report/help/usage;
no exit120 or stderr traceback in tested process failures; truthful source-only
scope and unchanged model/report/normal output. No public change before PASS.
