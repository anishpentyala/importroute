import contextlib
import importlib.machinery as machinery
import io
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from importroute import compare_routes, trace_imports
from importroute.__main__ import main


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.roots = [self.base / str(i) for i in range(3)]
        for root in self.roots:
            root.mkdir()

    def put(self, root, path):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('raise RuntimeError("must not run")\n')

    def compare(self, name='routeprobe', before=None, after=None, **kw):
        return compare_routes([name], self.roots if before is None else before,
                              list(reversed(self.roots)) if after is None else after, **kw)

    def test_origin_change_complete_traces_and_first_component(self):
        for root in self.roots[:2]:
            self.put(root, 'routeprobe/__init__.py')
            self.put(root, 'routeprobe/child.py')
        report = self.compare('routeprobe.child')
        self.assertEqual(report['status'], 'CHANGED')
        self.assertEqual(report['modules'][0]['first_changed_step'], 0)
        self.assertEqual(report['before'], trace_imports(['routeprobe.child'], self.roots))
        self.assertEqual(report['after'], trace_imports(['routeprobe.child'], self.roots[::-1]))
        self.assertNotIn('routeprobe', sys.modules)

    def test_namespace_order_and_duplicate_portions_are_changes(self):
        for root in self.roots:
            (root / 'routeprobe').mkdir()
        self.assertEqual(self.compare()['status'], 'CHANGED')
        self.assertEqual(self.compare(after=self.roots + self.roots[:1])['status'], 'CHANGED')

    def test_later_shadowed_changes_do_not_change_route(self):
        for root in self.roots:
            self.put(root, 'routeprobe.py')
        report = self.compare(before=self.roots, after=[self.roots[0], self.roots[2]])
        self.assertEqual(report['status'], 'UNCHANGED')
        self.assertIsNone(report['modules'][0]['first_changed_step'])
        self.assertNotEqual(report['before']['modules'][0]['steps'][0]['candidates'],
                            report['after']['modules'][0]['steps'][0]['candidates'])

    def test_missing_is_unchanged_not_located(self):
        report = self.compare()
        self.assertEqual(report['status'], 'UNCHANGED')
        self.assertEqual(report['modules'][0]['after_status'], 'MISSING')
        self.put(self.roots[0], 'routeprobe.py')
        self.assertEqual(self.compare(after=[self.roots[2]])['status'], 'CHANGED')

    def test_changed_child_of_same_namespace(self):
        for root in self.roots:
            (root / 'routeprobe').mkdir()
        self.put(self.roots[0], 'routeprobe/child.py')
        report = self.compare('routeprobe.child', after=self.roots[:2])
        self.assertEqual(report['modules'][0]['first_changed_step'], 0)

    def test_child_appears_and_parent_module_blocks(self):
        self.put(self.roots[0], 'routeprobe.py')
        self.put(self.roots[1], 'routeprobe/child.py')
        report = self.compare('routeprobe.child', before=self.roots[:1], after=self.roots[1:])
        self.assertEqual(report['modules'][0]['before_status'], 'PARENT_NOT_PACKAGE')
        self.assertEqual(report['modules'][0]['after_status'], 'LOCATED')
        self.assertEqual(report['status'], 'CHANGED')

    def test_incomplete_dominates_changes_and_no_first_witness(self):
        self.put(self.roots[0], 'routeprobe.py')
        report = self.compare(after=[self.roots[0], self.roots[0] / 'routeprobe.py'])
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertIsNone(report['modules'][0]['first_changed_step'])
        self.assertTrue(report['after']['modules'][0]['steps'][0]['errors'])
        self.assertEqual(self.compare('sys')['status'], 'INCOMPLETE')

    def test_scan_limits_are_separate_and_cannot_pass_partially(self):
        self.put(self.roots[0], 'routeprobe.py')
        with patch('importroute.core.MAX_ENTRIES', 1):
            self.assertEqual(self.compare(before=self.roots[:1], after=self.roots[:1])['status'],
                             'UNCHANGED')
        self.put(self.roots[1], 'other.py')
        with patch('importroute.core.MAX_ENTRIES', 1):
            self.assertEqual(self.compare()['status'], 'INCOMPLETE')

    def test_generator_modules_and_no_input_mutation(self):
        self.put(self.roots[0], 'routeprobe.py')
        roots = list(self.roots)
        report = compare_routes(iter(['routeprobe', 'missingprobe']), roots, roots)
        self.assertEqual([r['module'] for r in report['modules']], ['routeprobe', 'missingprobe'])
        self.assertEqual(roots, self.roots)
        self.assertEqual(report['status'], 'UNCHANGED')

    def test_invalid_inputs(self):
        for modules, before, after in [('routeprobe', self.roots, self.roots),
                                       (['routeprobe'], [], self.roots),
                                       (['routeprobe'], self.roots, []),
                                       (['bad.name!'], self.roots, self.roots)]:
            with self.assertRaises(ValueError):
                compare_routes(modules, before, after)

    def test_expectation_is_not_comparison_pass(self):
        self.put(self.roots[0], 'routeprobe.py')
        report = self.compare(before=self.roots, after=self.roots, expected_root=self.roots[2])
        self.assertEqual(report['status'], 'UNCHANGED')
        self.assertEqual(report['modules'][0]['after_status'], 'EXPECTATION_FAILED')

    def test_lexical_symlink_origins_not_physical_code_equality(self):
        self.put(self.roots[0], 'routeprobe.py')
        (self.roots[1] / 'routeprobe.py').symlink_to(self.roots[0] / 'routeprobe.py')
        self.assertEqual(self.compare(before=self.roots[:1], after=self.roots[1:2])['status'],
                         'CHANGED')

    def test_cli_json_human_and_0_1_2_3(self):
        self.put(self.roots[0], 'routeprobe.py')
        base = ['routeprobe', '--path', str(self.roots[0])]
        for path, expected in [(self.roots[0], 0), (self.roots[1], 1),
                               (self.roots[0] / 'routeprobe.py', 3)]:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(base + ['--compare-path', str(path), '--json']), expected)
            report = json.loads(output.getvalue())
            self.assertEqual(report['format'], 'importroute-comparison/v1')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(base + ['--compare-path', str(self.roots[1])]), 1)
        self.assertIn('MISSING', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['bad.!', '--path', str(self.roots[0]),
                                   '--compare-path', str(self.roots[1]), '--json']), 2)
        class Short(io.StringIO):
            def write(self, text):
                return 0
        with contextlib.redirect_stdout(Short()):
            self.assertEqual(main(base + ['--compare-path', str(self.roots[0])]), 2)

    def test_independent_native_finder_layout_oracle(self):
        # 5 x 5 root layouts, 6 ordered root plans (including duplicates),
        # every before/after pair = 900 comparisons, top and child names.
        layouts = ['empty', 'module', 'namespace', 'package', 'child']
        plans = [(0,), (1,), (0, 1), (1, 0), (0, 0, 1), (1, 0, 1)]
        def native(name, roots):
            rows = []
            for index, component in enumerate(name.split('.')):
                full = '.'.join(name.split('.')[:index + 1])
                spec = machinery.PathFinder.find_spec(full, [str(r) for r in roots])
                if spec is None:
                    rows.append((full, None))
                    return 'MISSING', rows
                locations = None if spec.submodule_search_locations is None else list(
                    spec.submodule_search_locations)
                kind = 'namespace' if spec.loader is None else ('package' if locations is not None
                                                               else 'module')
                rows.append((full, kind, spec.origin, locations or []))
                if index < len(name.split('.')) - 1 and kind == 'module':
                    return 'PARENT_NOT_PACKAGE', rows
                roots = locations or []
            return 'LOCATED', rows
        for a, b in itertools.product(layouts, repeat=2):
            with tempfile.TemporaryDirectory() as tmp:
                roots = [Path(tmp) / str(i) for i in range(2)]
                for root, layout in zip(roots, (a, b)):
                    root.mkdir()
                    if layout == 'module':
                        self.put(root, 'routeprobe.py')
                    if layout in ('namespace', 'package', 'child'):
                        (root / 'routeprobe').mkdir()
                    if layout == 'package':
                        self.put(root, 'routeprobe/__init__.py')
                    if layout == 'child':
                        self.put(root, 'routeprobe/child.py')
                for name in ['routeprobe', 'routeprobe.child']:
                    for first, second in itertools.product(plans, repeat=2):
                        old, new = [[roots[i] for i in plan] for plan in (first, second)]
                        expected = 'UNCHANGED' if native(name, old) == native(name, new) else 'CHANGED'
                        self.assertEqual(compare_routes([name], old, new)['status'], expected,
                                         (a, b, name, first, second))


if __name__ == '__main__':
    unittest.main()
