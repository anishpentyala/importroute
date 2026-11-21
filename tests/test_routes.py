import contextlib
import importlib.machinery as machinery
import io
import itertools
import json
import os
import py_compile
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from importroute import trace_imports
from importroute.__main__ import main


def touch(path, text='pass\n'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def item(report):
    return report['modules'][0]


def selection(report):
    return item(report)['steps'][-1]['selection']


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.roots = [self.base / str(n) for n in range(3)]
        for root in self.roots:
            root.mkdir()

    def trace(self, name='routeprobe', **options):
        return trace_imports([name], self.roots, **options)

    def test_single_source_and_missing(self):
        self.assertEqual(item(self.trace())['status'], 'MISSING')
        touch(self.roots[0] / 'routeprobe.py')
        report = self.trace()
        self.assertEqual(report['status'], 'LOCATED')
        self.assertEqual(selection(report)['origin'], str(self.roots[0] / 'routeprobe.py'))
        self.assertEqual(selection(report)['kind'], 'module')

    def test_package_beats_module_within_root(self):
        touch(self.roots[0] / 'routeprobe.py')
        touch(self.roots[0] / 'routeprobe' / '__init__.py')
        report = self.trace()
        self.assertEqual(selection(report)['kind'], 'package')
        candidates = item(report)['steps'][0]['candidates']
        self.assertEqual([c['disposition'] for c in candidates],
                         ['selected', 'lower_priority_same_root'])

    def test_earlier_module_beats_later_package(self):
        touch(self.roots[0] / 'routeprobe.py')
        touch(self.roots[1] / 'routeprobe' / '__init__.py')
        report = self.trace()
        self.assertEqual(selection(report)['kind'], 'module')
        self.assertEqual(item(report)['steps'][0]['candidates'][1]['disposition'], 'later_search_root')

    def test_namespace_merges_in_order_with_duplicate_roots(self):
        for root in self.roots:
            (root / 'routeprobe').mkdir()
        report = trace_imports(['routeprobe'], self.roots + [self.roots[0]])
        self.assertEqual(selection(report)['kind'], 'namespace')
        self.assertEqual(selection(report)['locations'],
                         [str(root / 'routeprobe') for root in self.roots + [self.roots[0]]])

    def test_later_concrete_discards_earlier_namespace_portions(self):
        (self.roots[0] / 'routeprobe').mkdir()
        touch(self.roots[1] / 'routeprobe' / '__init__.py')
        touch(self.roots[2] / 'routeprobe.py')
        report = self.trace()
        self.assertEqual(selection(report)['origin'], str(self.roots[1] / 'routeprobe' / '__init__.py'))
        self.assertEqual(item(report)['steps'][0]['candidates'][0]['disposition'],
                         'namespace_discarded_by_concrete')

    def test_module_beats_namespace_at_same_root(self):
        (self.roots[0] / 'routeprobe').mkdir()
        touch(self.roots[0] / 'routeprobe.py')
        self.assertEqual(selection(self.trace())['kind'], 'module')

    def test_nested_namespace_and_regular_package(self):
        for root in self.roots:
            (root / 'routeprobe').mkdir()
        touch(self.roots[1] / 'routeprobe' / 'child' / '__init__.py')
        touch(self.roots[1] / 'routeprobe' / 'child' / 'leaf.py')
        report = self.trace('routeprobe.child.leaf')
        self.assertEqual(item(report)['status'], 'LOCATED')
        self.assertEqual([s['selection']['kind'] for s in item(report)['steps']],
                         ['namespace', 'package', 'module'])
        self.assertEqual(item(report)['steps'][2]['search_roots'],
                         [str(self.roots[1] / 'routeprobe' / 'child')])

    def test_regular_parent_does_not_fall_back_to_other_roots_for_child(self):
        touch(self.roots[0] / 'routeprobe' / '__init__.py')
        touch(self.roots[1] / 'routeprobe' / 'child.py')
        report = self.trace('routeprobe.child')
        self.assertEqual(item(report)['status'], 'MISSING')
        self.assertEqual(len(item(report)['steps']), 2)

    def test_nonpackage_parent_blocks_children(self):
        touch(self.roots[0] / 'routeprobe.py')
        report = self.trace('routeprobe.child.leaf')
        self.assertEqual(item(report)['status'], 'PARENT_NOT_PACKAGE')
        self.assertEqual(len(item(report)['steps']), 1)
        self.assertEqual(report['status'], 'FAILED')

    def test_pyc_and_extension_candidates_not_executed(self):
        touch(self.roots[0] / 'routeprobe.py')
        py_compile.compile(str(self.roots[0] / 'routeprobe.py'),
                           cfile=str(self.roots[0] / 'routeprobe.pyc'), doraise=True)
        touch(self.roots[0] / ('routeprobe' + machinery.EXTENSION_SUFFIXES[0]), 'not a binary')
        report = self.trace()
        self.assertEqual(selection(report)['storage'], 'extension')
        # PathFinder locates but does not load this deliberately invalid binary.
        native = machinery.PathFinder.find_spec('routeprobe', [str(r) for r in self.roots])
        self.assertEqual(selection(report)['origin'], native.origin)
        (self.roots[0] / ('routeprobe' + machinery.EXTENSION_SUFFIXES[0])).unlink()
        self.assertEqual(selection(self.trace())['storage'], 'source')
        (self.roots[0] / 'routeprobe.py').unlink()
        self.assertEqual(selection(self.trace())['storage'], 'bytecode')

    def test_pycache_alone_does_not_become_legacy_pyc_candidate(self):
        source = self.roots[0] / 'routeprobe.py'
        touch(source)
        py_compile.compile(str(source), doraise=True)
        source.unlink()
        self.assertEqual(item(self.trace())['status'], 'MISSING')

    def test_expected_root_checks_all_components_and_prefix_boundary(self):
        touch(self.roots[0] / 'routeprobe.py')
        self.assertEqual(self.trace(expected_root=self.roots[0])['status'], 'LOCATED')
        self.assertEqual(item(self.trace(expected_root=self.roots[1]))['status'], 'EXPECTATION_FAILED')
        sibling = self.base / '00'
        sibling.mkdir()
        touch(sibling / 'routeprobe.py')
        report = trace_imports(['routeprobe'], [sibling], expected_root=self.roots[0])
        self.assertFalse(item(report)['expectation']['matches'])

    def test_expected_root_checks_all_namespace_portions(self):
        for root in self.roots:
            (root / 'routeprobe').mkdir()
        touch(self.roots[0] / 'routeprobe' / 'child.py')
        report = self.trace('routeprobe.child', expected_root=self.roots[0])
        self.assertEqual(item(report)['status'], 'EXPECTATION_FAILED')
        self.assertEqual(len(item(report)['expectation']['outside']), 2)

    @unittest.skipUnless(hasattr(os, 'symlink'), 'requires symlinks')
    def test_expectation_follows_symlinks_not_lexical_containment(self):
        touch(self.roots[1] / 'actual.py')
        (self.roots[0] / 'routeprobe.py').symlink_to(self.roots[1] / 'actual.py')
        report = self.trace(expected_root=self.roots[0])
        self.assertEqual(item(report)['status'], 'EXPECTATION_FAILED')
        self.assertEqual(item(report)['expectation']['outside'][0]['physical_path'],
                         str(self.roots[1] / 'actual.py'))

    def test_missing_roots_are_explicitly_ignored(self):
        touch(self.roots[0] / 'routeprobe.py')
        report = trace_imports(['routeprobe'], [self.base / 'missing', self.roots[0]])
        self.assertEqual(report['status'], 'LOCATED')
        self.assertEqual(item(report)['steps'][0]['ignored_roots'][0]['reason'], 'missing_root')

    def test_non_directory_root_is_incomplete_even_after_a_winner(self):
        archive = self.base / 'archive.zip'
        archive.write_bytes(b'not an archive')
        touch(self.roots[0] / 'routeprobe.py')
        report = trace_imports(['routeprobe'], [self.roots[0], archive])
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertTrue(item(report)['steps'][0]['errors'])
        self.assertIsNotNone(selection(report))

    def test_permission_error_cannot_be_silently_skipped(self):
        touch(self.roots[1] / 'routeprobe.py')
        original = os.scandir
        def fail_one(path):
            if str(path) == str(self.roots[0]):
                raise PermissionError('test denied')
            return original(path)
        with patch('importroute.core.os.scandir', side_effect=fail_one):
            report = self.trace()
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(item(report)['steps'][0]['errors'][0]['error'], 'PermissionError')

    def test_bounded_entry_enumeration_and_no_partial_pass(self):
        for i in range(5):
            touch(self.roots[0] / ('unrelated' + str(i)))
        touch(self.roots[1] / 'routeprobe.py')
        with patch('importroute.core.MAX_ENTRIES', 3):
            report = self.trace()
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['directory_entries_scanned'], 4)
        self.assertTrue(any(e['error'] == 'ScanLimitError' for e in item(report)['steps'][0]['errors']))

    def test_no_target_execution_hooks_source_reads_or_target_writes(self):
        marker = self.base / 'side-effect'
        touch(self.roots[0] / 'routeprobe' / '__init__.py',
              'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\nraise RuntimeError()\n')
        touch(self.roots[0] / 'routeprobe' / 'child.py', 'raise RuntimeError()\n')
        before = {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        class Hook:
            def find_spec(self, *args):
                raise AssertionError('custom meta hook called')
        with patch('sys.meta_path', [Hook()]), patch('sys.path_hooks', [Hook()]), \
                patch('builtins.open', side_effect=AssertionError('source opened')):
            report = self.trace('routeprobe.child')
        self.assertEqual(report['status'], 'LOCATED')
        self.assertFalse(marker.exists())
        self.assertNotIn('routeprobe', sys.modules)
        after = {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_native_dotted_spec_baseline_executes_parent_but_trace_does_not(self):
        marker = self.base / 'parent-ran'
        touch(self.roots[0] / 'routeprobe' / '__init__.py',
              'from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        touch(self.roots[0] / 'routeprobe' / 'child.py')
        self.assertEqual(self.trace('routeprobe.child')['status'], 'LOCATED')
        self.assertFalse(marker.exists())
        runner = ('import importlib.util,sys;sys.path.insert(0,sys.argv[1]);'
                  'assert importlib.util.find_spec("routeprobe.child") is not None')
        subprocess.run([sys.executable, '-I', '-S', '-c', runner, str(self.roots[0])],
                       check=True, timeout=10, capture_output=True)
        self.assertTrue(marker.exists())

    def test_builtin_and_frozen_names_cannot_pass_directory_expectation(self):
        for name in ('sys', 'os'):
            if name == 'os' and machinery.FrozenImporter.find_spec(name) is None:
                continue
            touch(self.roots[0] / (name + '.py'))
            report = trace_imports([name], self.roots, expected_root=self.roots[0])
            self.assertEqual(report['status'], 'INCOMPLETE')
            self.assertEqual(item(report)['steps'], [])

    def test_exact_case_unicode_and_literal_paths(self):
        touch(self.roots[0] / 'Routeprobe.py')
        self.assertEqual(item(self.trace())['status'], 'MISSING')
        touch(self.roots[0] / 'Ω.py')
        self.assertEqual(trace_imports(['Ω'], self.roots)['status'], 'LOCATED')
        literal = self.base / 'literal*root'
        literal.mkdir()
        touch(literal / 'routeprobe.py')
        self.assertEqual(trace_imports(['routeprobe'], [literal])['status'], 'LOCATED')

    def test_roots_are_absolutized_without_environment_or_tilde_expansion(self):
        report = trace_imports(['routeprobe'], ['~/literal', '$HOME/literal'])
        self.assertEqual(report['search_paths'], [os.path.abspath('~/literal'), os.path.abspath('$HOME/literal')])
        self.assertEqual(trace_imports(['routeprobe'], [''])['search_paths'], [os.getcwd()])

    def test_validation_precedes_filesystem_scan(self):
        bad_modules = [[], 'routeprobe', [''], ['.routeprobe'], ['routeprobe.'],
                       ['a/b'], ['..'], ['a\x00b'], ['a-b'], ['a.' * 33 + 'b'], [12], ['ok'] * 129]
        with patch('importroute.core.os.scandir', side_effect=AssertionError('scan started')):
            for values in bad_modules:
                with self.subTest(values=values), self.assertRaises((ValueError, TypeError)):
                    trace_imports(values, self.roots)
            for paths in ([], 'one', b'one', [b'one'], [12], ['a\x00b'], ['one'] * 65):
                with self.subTest(paths=paths), self.assertRaises((ValueError, TypeError)):
                    trace_imports(['routeprobe'], paths)

    def test_infinite_generators_are_bounded(self):
        count = []
        def roots():
            while True:
                count.append(1)
                yield 'root'
        with self.assertRaises(ValueError):
            trace_imports(['routeprobe'], roots())
        self.assertEqual(len(count), 65)

    def test_directory_cache_is_query_local_and_not_a_persistent_stale_result(self):
        first = self.trace()
        touch(self.roots[0] / 'routeprobe.py')
        second = self.trace()
        self.assertEqual(first['status'], 'FAILED')
        self.assertEqual(second['status'], 'LOCATED')

    def test_multiple_query_aggregation_keeps_all_outcomes(self):
        touch(self.roots[0] / 'routeprobe.py')
        report = trace_imports(['routeprobe', 'missingprobe', 'sys'], self.roots)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual([r['status'] for r in report['modules']], ['LOCATED', 'MISSING', 'INCOMPLETE'])

    def test_native_filefinder_precedence_all_two_root_layout_pairs(self):
        # Independent standard-library finder oracle, no production helpers.
        for a, b in itertools.product(range(5), repeat=2):
            with self.subTest(a=a, b=b), tempfile.TemporaryDirectory() as directory:
                roots = [Path(directory) / str(i) for i in range(2)]
                for root, layout in zip(roots, (a, b)):
                    root.mkdir()
                    if layout in (1, 3, 4):
                        (root / 'routeprobe').mkdir()
                    if layout in (2, 4):
                        touch(root / 'routeprobe.py')
                    if layout in (3, 4):
                        touch(root / 'routeprobe' / '__init__.py')
                native = machinery.PathFinder.find_spec('routeprobe', [str(r) for r in roots])
                report = trace_imports(['routeprobe'], roots)
                if native is None:
                    self.assertEqual(item(report)['status'], 'MISSING')
                else:
                    self.assertEqual(selection(report)['origin'], native.origin)
                    expected_locations = (list(native.submodule_search_locations)
                                          if native.submodule_search_locations is not None else [])
                    self.assertEqual(selection(report)['locations'], expected_locations)

    def test_seeded_nested_layouts_against_actual_harmless_imports(self):
        rng = random.Random(881027)
        runner = '''import importlib,json,sys
sys.path=json.loads(sys.argv[1])
name='routeprobe.child.leaf'
try:
 m=importlib.import_module(name)
 result={'status':'LOCATED','origin':getattr(m,'__file__',None),'locations':list(getattr(m,'__path__',[]))}
except ModuleNotFoundError:
 blocked=any(prefix in sys.modules and not hasattr(sys.modules[prefix],'__path__') for prefix in ['routeprobe','routeprobe.child'])
 result={'status':'PARENT_NOT_PACKAGE' if blocked else 'MISSING'}
print(json.dumps(result))
'''
        for case in range(120):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                roots = [Path(directory) / str(i) for i in range(3)]
                for root in roots:
                    root.mkdir()
                    current = root
                    for part in ('routeprobe', 'child', 'leaf'):
                        layout = rng.randrange(5)
                        if layout in (2, 4):
                            touch(current / (part + '.py'))
                        if layout in (1, 3, 4):
                            current = current / part
                            current.mkdir(exist_ok=True)
                            if layout in (3, 4):
                                touch(current / '__init__.py')
                        else:
                            break
                result = subprocess.run([sys.executable, '-I', '-S', '-c', runner,
                                         json.dumps([str(r) for r in roots])],
                                        capture_output=True, text=True, timeout=10, check=True)
                native = json.loads(result.stdout)
                report = trace_imports(['routeprobe.child.leaf'], roots)
                self.assertEqual(item(report)['status'], native['status'])
                if native['status'] == 'LOCATED':
                    self.assertEqual(selection(report)['origin'], native['origin'])
                    self.assertEqual(selection(report)['locations'], native['locations'])


    def test_package_and_module_storage_order_against_native_finder(self):
        for package in (False, True):
            with self.subTest(package=package), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stem = root / 'routeprobe'
                if package:
                    stem.mkdir()
                    stem = stem / '__init__'
                paths = [Path(str(stem) + suffix) for suffix in
                         [machinery.EXTENSION_SUFFIXES[0], '.py', '.pyc']]
                for path in paths:
                    touch(path, 'not loadable, only locate')
                for remaining in range(3):
                    native = machinery.PathFinder.find_spec('routeprobe', [str(root)])
                    report = trace_imports(['routeprobe'], [root])
                    self.assertEqual(selection(report)['origin'], native.origin)
                    self.assertEqual(selection(report)['origin'], str(paths[remaining]))
                    paths[remaining].unlink()
                    machinery.PathFinder.invalidate_caches()

    def test_broken_links_and_nonregular_files_are_not_candidates(self):
        (self.roots[0] / 'routeprobe.py').mkdir()
        (self.roots[1] / 'routeprobe.py').symlink_to(self.base / 'missing')
        touch(self.roots[2] / 'routeprobe.py')
        report = self.trace()
        self.assertEqual(selection(report)['origin'], str(self.roots[2] / 'routeprobe.py'))
        self.assertEqual(len(item(report)['steps'][0]['candidates']), 1)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires fifo')
    def test_fifo_is_not_opened_or_selected(self):
        os.mkfifo(self.roots[0] / 'routeprobe.py')
        self.assertEqual(item(self.trace())['status'], 'MISSING')

    def test_directory_budget_does_not_restart_for_later_queries(self):
        for index in range(5):
            touch(self.roots[0] / str(index))
        with patch('importroute.core.MAX_ENTRIES', 3):
            report = trace_imports(['firstprobe', 'secondprobe'], self.roots)
        self.assertEqual(report['directory_entries_scanned'], 4)
        self.assertEqual([r['status'] for r in report['modules']], ['INCOMPLETE'] * 2)

    def test_expectation_failure_to_resolve_selected_file_is_incomplete(self):
        touch(self.roots[0] / 'routeprobe.py')
        original = os.path.realpath
        def fail_file(path, **options):
            if str(path).endswith('routeprobe.py'):
                raise FileNotFoundError('simulated concurrent removal')
            return original(path, **options)
        with patch('importroute.core.os.path.realpath', side_effect=fail_file):
            report = self.trace(expected_root=self.roots[0])
        self.assertEqual(report['status'], 'INCOMPLETE')


class CLITests(unittest.TestCase):
    def invoke(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(arguments)
        return code, output.getvalue()

    def test_cli_json_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            touch(Path(directory) / 'routeprobe.py')
            code, text = self.invoke(['routeprobe', '--path', directory, '--json'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(text)['status'], 'LOCATED')
            code, text = self.invoke(['routeprobe', '--path', directory])
            self.assertEqual(code, 0)
            self.assertIn('selected: module', text)
            self.assertIn('not runtime import verification', text)
            self.assertEqual(self.invoke(['missingprobe', '--path', directory, '--json'])[0], 1)
            self.assertEqual(self.invoke(['sys', '--path', directory, '--json'])[0], 3)
            self.assertEqual(self.invoke(['../bad', '--path', directory, '--json'])[0], 2)

    def test_missing_path_flag_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(['routeprobe'])
        self.assertEqual(raised.exception.code, 2)

    def test_closed_and_short_streams_are_output_failures(self):
        closed = io.StringIO()
        closed.close()
        with contextlib.redirect_stdout(closed):
            self.assertEqual(main(['routeprobe', '--path', '/missing/root']), 2)
        class Short(io.StringIO):
            def write(self, value):
                return super().write(value[:4])
        with contextlib.redirect_stdout(Short()):
            self.assertEqual(main(['routeprobe', '--path', '/missing/root']), 2)

    def test_human_output_escapes_control_characters_in_paths_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / 'bad\nroot.zip'
            bad.touch()
            code, text = self.invoke(['routeprobe', '--path', str(bad)])
            self.assertEqual(code, 3)
            self.assertNotIn('bad\nroot', text)
            self.assertIn('bad\\nroot', text)
            with patch('importroute.__main__.trace_imports',
                       side_effect=ValueError('bad\nmessage')):
                code, text = self.invoke(['routeprobe', '--path', directory])
            self.assertEqual(code, 2)
            self.assertEqual(text.count('\n'), 1)
            self.assertIn('bad\\nmessage', text)

    @unittest.skipUnless(os.path.exists('/dev/full'), 'requires /dev/full')
    def test_real_process_output_failure(self):
        with open('/dev/full', 'wb') as destination:
            result = subprocess.run([sys.executable, '-m', 'importroute', 'missingprobe',
                                     '--path', '/missing/root', '--json'], stdout=destination,
                                    stderr=subprocess.PIPE, timeout=10, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
