"""Command-line display and strict process exit handling."""
import argparse
import inspect
import json
import sys
from functools import partial

from .comparison import compare_routes
from .core import trace_imports

CODES = {'LOCATED': 0, 'FAILED': 1, 'INVALID': 2, 'INCOMPLETE': 3,
         'UNCHANGED': 0, 'CHANGED': 1}


def _deliver(stream, text):
    if stream is None:
        raise OSError('output stream is unavailable')
    accepted = stream.write(text)
    if type(accepted) is not int or accepted != len(text):
        raise OSError('output stream did not accept complete text')
    stream.flush()


_PARSER_DEFAULT = object()


class _Parser(argparse.ArgumentParser):
    def _print_message(self, message, file=_PARSER_DEFAULT):
        if message:
            _deliver(sys.stderr if file is _PARSER_DEFAULT else file, message)


def _human(report):
    if report['status'] == 'INVALID':
        return 'INVALID: ' + repr(report['error']) + '\n'
    if report['format'] == 'importroute-comparison/v1':
        lines = ['Declared path-plan comparison: ' + report['status']]
        for item in report['modules']:
            lines.append(item['module'] + ': ' + item['status'] + ' (' +
                         item['before_status'] + ' -> ' + item['after_status'] + ')')
            if item['first_changed_step'] is not None:
                lines.append('  first changed component index: ' +
                             str(item['first_changed_step']))
        lines.append(report['scope'])
        lines.append('Use --json for complete before/after traces.')
        return '\n'.join(lines) + '\n'
    lines = ['Filesystem import routes, not runtime import verification.']
    for item in report['modules']:
        lines.append(item['module'] + ': ' + item['status'])
        if 'reason' in item:
            lines.append('  ' + repr(item['reason']))
        for step in item['steps']:
            lines.append('  ' + step['module'])
            for candidate in step['candidates']:
                location = (repr(candidate['origin']) if candidate['origin'] else
                            ', '.join(repr(path) for path in candidate['locations']))
                lines.append('    ' + candidate['disposition'] + ': ' + candidate['kind'] + ' ' + location)
            for error in step['errors']:
                lines.append('    unchecked root ' + repr(error['root']) + ': ' + repr(error['detail']))
            if step['selection'] is None:
                lines.append('    no candidate found in checked directories')
        for outside in item.get('expectation', {}).get('outside', []):
            lines.append('  outside expected root: ' + repr(outside['physical_path']))
    lines.append(report['scope'])
    return '\n'.join(lines) + '\n'


def _run(argv=None):
    options = {}
    if 'color' in inspect.signature(argparse.ArgumentParser).parameters:
        options['color'] = False
    if 'color' in inspect.signature(argparse.HelpFormatter).parameters:
        options['formatter_class'] = partial(argparse.HelpFormatter, color=False)
    parser = _Parser(
        description='Explain explicit Python filesystem routes without importing target packages.',
        **options)
    parser.add_argument('modules', nargs='+', help='absolute dotted module identifiers, at most 128')
    parser.add_argument('--path', action='append', required=True,
                        help='ordered search directory, repeat for each root; at most 64')
    parser.add_argument('--expect-under', help='require every selected component under this directory')
    parser.add_argument('--compare-path', action='append',
                        help='candidate ordered roots; compares with --path, repeat for each root')
    parser.add_argument('--json', action='store_true', help='emit the full versioned JSON report')
    try:
        args = parser.parse_args(argv)
    except (OSError, ValueError, AttributeError):
        return 2, True
    try:
        if args.compare_path is None:
            report = trace_imports(args.modules, args.path, expected_root=args.expect_under)
        else:
            report = compare_routes(args.modules, args.path, args.compare_path,
                                    expected_root=args.expect_under)
    except (OSError, ValueError, TypeError) as exc:
        report = {'format': 'importroute/v1', 'status': 'INVALID', 'error': str(exc)}
    payload = (json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True) + '\n'
               if args.json else _human(report))
    try:
        _deliver(sys.stdout, payload)
    except (OSError, ValueError, AttributeError):
        return 2, True
    return CODES[report['status']], False


def main(argv=None):
    """Return the code without replacing or closing caller-owned stdout."""
    return _run(argv)[0]


def entrypoint():
    """Own process shutdown, including argparse's successful SystemExit paths."""
    try:
        code, _ = _run()
    except SystemExit as exc:
        code = exc.code
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name)
        if stream is None:
            continue
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            setattr(sys, name, None)
            code = 2
    return code


if __name__ == '__main__':
    sys.exit(entrypoint())
