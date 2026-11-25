"""Compare two declared path plans against the observed filesystem, not history."""
from .core import MAX_MODULES, _bounded, trace_imports


def _route(item):
    return {'status': item['status'],
            'steps': [{'module': step['module'], 'selection': step['selection']}
                      for step in item['steps']]}


def compare_routes(modules, before_paths, after_paths, *, expected_root=None):
    """Compare selection at every component, including ordered namespace portions.

    Both plans are observed now, sequentially. This is not a before/after file
    snapshot or proof of runtime behavior. Each side has its own scan budget.
    Missing names may be UNCHANGED; that does not mean they can be imported.
    """
    modules = _bounded(modules, MAX_MODULES, 'modules')
    before = trace_imports(modules, before_paths, expected_root=expected_root)
    after = trace_imports(modules, after_paths, expected_root=expected_root)
    rows = []
    for old, new in zip(before['modules'], after['modules']):
        incomplete = 'INCOMPLETE' in (old['status'], new['status'])
        old_route, new_route = _route(old), _route(new)
        different = old_route != new_route
        first = None
        if not incomplete:
            for index in range(max(len(old_route['steps']), len(new_route['steps']))):
                a = old_route['steps'][index] if index < len(old_route['steps']) else None
                b = new_route['steps'][index] if index < len(new_route['steps']) else None
                if a != b:
                    first = index
                    break
        rows.append({'module': old['module'],
                     'status': 'INCOMPLETE' if incomplete else
                               'CHANGED' if different else 'UNCHANGED',
                     'before_status': old['status'], 'after_status': new['status'],
                     'first_changed_step': first})
    status = ('INCOMPLETE' if any(r['status'] == 'INCOMPLETE' for r in rows) else
              'CHANGED' if any(r['status'] == 'CHANGED' for r in rows) else 'UNCHANGED')
    return {'format': 'importroute-comparison/v1', 'status': status,
            'modules': rows, 'before': before, 'after': after,
            'scope': 'sequential observations of two declared path plans; not runtime imports, '
                     'historical snapshots, loadability, code equality or rollout safety',
            'comparison': 'per-module status and every component selection; ordered namespace '
                          'locations and lexical origins; not discarded candidates or root positions',
            'limits': 'each side has an independent normal trace scan budget'}
