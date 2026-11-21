"""Bounded directory lookup. No target module or path hook is executed."""
import importlib.machinery as machinery
import os
import stat
import sys
from itertools import islice

MAX_MODULES = 128
MAX_ROOTS = 64
MAX_DEPTH = 32
MAX_ENTRIES = 100_000
SCOPE = ('exact-case directory FileFinder model only; not a runtime import, '
         'loadability, code-safety or atomic-filesystem certificate')


class ScanLimitError(Exception):
    pass


def _bounded(values, limit, label):
    if isinstance(values, (str, bytes, os.PathLike)):
        raise ValueError(label + ' must be an iterable, not one string or path')
    result = list(islice(values, limit + 1))
    if not result or len(result) > limit:
        raise ValueError(label + ' requires 1 to ' + str(limit) + ' entries')
    return result


def _path(value):
    value = os.fspath(value)
    if not isinstance(value, str) or '\x00' in value:
        raise ValueError('paths must be NUL-free strings or string-valued path objects')
    return os.path.abspath(value)


def _mode(path):
    try:
        return os.stat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None


class _Probe:
    def __init__(self):
        self.cache = {}
        self.entries = 0

    def names(self, path):
        if path not in self.cache:
            if self.entries >= MAX_ENTRIES:
                raise ScanLimitError('directory-entry budget exceeded')
            names = set()
            with os.scandir(path) as entries:
                for entry in entries:
                    self.entries += 1
                    if self.entries > MAX_ENTRIES:
                        raise ScanLimitError('directory-entry budget exceeded')
                    names.add(entry.name)
            self.cache[path] = names
        return self.cache[path]


def _suffixes():
    # CPython's default FileFinder loader order, not arbitrary sys.path_hooks.
    return [(suffix, kind) for suffixes, kind in (
        (machinery.EXTENSION_SUFFIXES, 'extension'),
        (machinery.SOURCE_SUFFIXES, 'source'),
        (machinery.BYTECODE_SUFFIXES, 'bytecode')) for suffix in suffixes]


def _scan(probe, root, name, root_position):
    mode = _mode(root)
    if mode is None:
        return [], 'missing_root'
    if not stat.S_ISDIR(mode):
        raise ValueError('non-directory search roots, including archives, are outside the model')
    names = probe.names(root)
    candidates = []
    directory = os.path.join(root, name)
    directory_mode = _mode(directory) if name in names else None
    package = directory_mode is not None and stat.S_ISDIR(directory_mode)
    package_names = probe.names(directory) if package else set()
    suffixes = _suffixes()
    for prefix, parent, available, candidate_kind in (
            ('__init__', directory, package_names, 'package'),
            (name, root, names, 'module')):
        for suffix, storage in suffixes:
            filename = prefix + suffix
            if filename not in available:
                continue
            origin = os.path.join(parent, filename)
            mode = _mode(origin)
            if mode is not None and stat.S_ISREG(mode):
                candidates.append({'root_position': root_position, 'root': root,
                                   'kind': candidate_kind, 'storage': storage,
                                   'origin': origin,
                                   'locations': [directory] if candidate_kind == 'package' else []})
    if package and not any(c['kind'] == 'package' for c in candidates):
        candidates.append({'root_position': root_position, 'root': root,
                           'kind': 'namespace', 'storage': None, 'origin': None,
                           'locations': [directory]})
    return candidates, None


def _step(probe, fullname, roots):
    candidates = []
    ignored = []
    errors = []
    for position, root in enumerate(roots, 1):
        try:
            found, reason = _scan(probe, root, fullname.rsplit('.', 1)[-1], position)
            candidates.extend(found)
            if reason:
                ignored.append({'root_position': position, 'root': root, 'reason': reason})
        except (OSError, ValueError, ScanLimitError) as exc:
            errors.append({'root_position': position, 'root': root,
                           'error': type(exc).__name__, 'detail': str(exc)})
    concrete = next((i for i, c in enumerate(candidates) if c['kind'] != 'namespace'), None)
    selected = ([concrete] if concrete is not None else
                [i for i, c in enumerate(candidates) if c['kind'] == 'namespace'])
    for index, candidate in enumerate(candidates):
        if index in selected:
            reason = 'selected' if concrete is not None else 'namespace_portion'
        elif candidate['kind'] == 'namespace':
            reason = 'namespace_discarded_by_concrete'
        elif candidate['root_position'] == candidates[concrete]['root_position']:
            reason = 'lower_priority_same_root'
        else:
            reason = 'later_search_root'
        candidate['disposition'] = reason
    selection = None
    if selected:
        chosen = candidates[selected[0]]
        selection = {'kind': chosen['kind'], 'storage': chosen['storage'],
                     'origin': chosen['origin'],
                     'locations': [location for i in selected for location in candidates[i]['locations']]}
    return {'module': fullname, 'search_roots': list(roots), 'candidates': candidates,
            'selection': selection, 'ignored_roots': ignored, 'errors': errors}


def _expectation(steps, expected):
    outside = []
    for step in steps:
        selection = step['selection']
        if selection is None:
            continue
        paths = ([selection['origin']] if selection['origin'] else selection['locations'])
        for path in paths:
            physical = os.path.realpath(path, strict=True)
            try:
                inside = os.path.commonpath([expected, physical]) == expected
            except ValueError:
                inside = False
            if not inside:
                outside.append({'module': step['module'], 'path': path, 'physical_path': physical})
    return {'root': expected, 'matches': not outside, 'outside': outside,
            'scope': 'every selected component, including all namespace portions; physical paths'}


def _trace(probe, module, roots, expected):
    top = module.split('.')[0]
    # These normal runtime finders precede the default path-based finder.
    # Do not pretend a declared directory candidate wins over them.
    builtin = top in sys.builtin_module_names
    frozen = machinery.FrozenImporter.find_spec(top) is not None
    if builtin or frozen:
        return {'module': module, 'status': 'INCOMPLETE', 'steps': [],
                'reason': 'top-level name has builtin or frozen precedence in this interpreter',
                'runtime_precedence': 'builtin' if builtin else 'frozen'}
    steps = []
    parts = module.split('.')
    status = 'LOCATED'
    for index in range(len(parts)):
        step = _step(probe, '.'.join(parts[:index + 1]), roots)
        steps.append(step)
        if step['errors']:
            status = 'INCOMPLETE'
            break
        selection = step['selection']
        if selection is None:
            status = 'MISSING'
            break
        if index < len(parts) - 1 and selection['kind'] == 'module':
            status = 'PARENT_NOT_PACKAGE'
            break
        roots = selection['locations']
    result = {'module': module, 'status': status, 'steps': steps}
    if expected is not None and status == 'LOCATED':
        try:
            result['expectation'] = _expectation(steps, expected)
            if not result['expectation']['matches']:
                result['status'] = 'EXPECTATION_FAILED'
        except OSError as exc:
            result['status'] = 'INCOMPLETE'
            result['reason'] = 'could not check physical-path expectation: ' + str(exc)
    return result


def trace_imports(modules, search_paths, *, expected_root=None):
    """Explain explicit ordered directory lookup without importing targets.

    This models default, exact-case CPython filesystem selection only. It never
    changes sys.path, calls path hooks, reads source or loads bytecode/binaries.
    Regular-package child lookup assumes its default directory __path__. Dynamic
    __path__, module cache, custom finders, .pth and archives are not evaluated.
    """
    modules = _bounded(modules, MAX_MODULES, 'modules')
    for module in modules:
        if (not isinstance(module, str) or len(module.split('.')) > MAX_DEPTH
                or not all(part.isidentifier() for part in module.split('.'))):
            raise ValueError('modules must be absolute dotted identifiers with at most 32 parts')
    roots = [_path(path) for path in _bounded(search_paths, MAX_ROOTS, 'search_paths')]
    expected = None
    if expected_root is not None:
        expected = os.path.realpath(_path(expected_root), strict=True)
        if not stat.S_ISDIR(os.stat(expected).st_mode):
            raise ValueError('expected_root must be an existing directory')
    probe = _Probe()
    reports = [_trace(probe, module, roots, expected) for module in modules]
    status = ('INCOMPLETE' if any(r['status'] == 'INCOMPLETE' for r in reports) else
              'FAILED' if any(r['status'] != 'LOCATED' for r in reports) else 'LOCATED')
    return {'format': 'importroute/v1', 'status': status, 'search_paths': roots,
            'modules': reports, 'directory_entries_scanned': probe.entries,
            'suffix_order': [{'suffix': suffix, 'storage': kind} for suffix, kind in _suffixes()],
            'scope': SCOPE,
            'assumptions': ['explicit roots only; not the target process sys.path',
                            'no custom import hooks or module-cache entries',
                            'regular packages keep their default directory __path__',
                            'no initializer execution or loadability check',
                            'directory observations may race with filesystem changes']}
