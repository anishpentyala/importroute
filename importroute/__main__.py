"""Command-line display and strict process exit handling."""
import argparse
import inspect
import json
import os
import sys
from functools import partial

from .core import trace_imports

CODES = {'LOCATED': 0, 'FAILED': 1, 'INVALID': 2, 'INCOMPLETE': 3}


def _human(report):
    if report['status'] == 'INVALID':
        return 'INVALID: ' + repr(report['error']) + '\n'
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
    parser = argparse.ArgumentParser(
        description='Explain explicit Python filesystem routes without importing target packages.',
        **options)
    parser.add_argument('modules', nargs='+', help='absolute dotted module identifiers, at most 128')
    parser.add_argument('--path', action='append', required=True,
                        help='ordered search directory, repeat for each root; at most 64')
    parser.add_argument('--expect-under', help='require every selected component under this directory')
    parser.add_argument('--json', action='store_true', help='emit the full versioned JSON report')
    args = parser.parse_args(argv)
    try:
        report = trace_imports(args.modules, args.path, expected_root=args.expect_under)
    except (OSError, ValueError, TypeError) as exc:
        report = {'format': 'importroute/v1', 'status': 'INVALID', 'error': str(exc)}
    payload = (json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True) + '\n'
               if args.json else _human(report))
    try:
        if sys.stdout.write(payload) != len(payload):
            return 2, True
        sys.stdout.flush()
    except (OSError, ValueError, AttributeError):
        return 2, True
    return CODES[report['status']], False


def main(argv=None):
    """Return the code without replacing or closing caller-owned stdout."""
    return _run(argv)[0]


def entrypoint():
    code, failed = _run()
    if failed:
        try:
            descriptor = sys.stdout.fileno()
            with open(os.devnull, 'w') as sink:
                os.dup2(sink.fileno(), descriptor)
        except (OSError, ValueError, AttributeError):
            sys.stdout = open(os.devnull, 'w')
    return code


if __name__ == '__main__':
    sys.exit(entrypoint())
