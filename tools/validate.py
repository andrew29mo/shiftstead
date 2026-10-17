"""A new validation cannot inherit success from an older JSON/HTML artifact."""
import sys
import os
import secrets
import time
from pathlib import Path
from tools.evidence import environment, provenance, atomic_json
from tools.process import run_stage


def main():
    Path('results').mkdir(exist_ok=True)
    source = provenance()
    run_id = secrets.token_hex(16)
    prior_run = os.environ.get('SHIFTSTEAD_VALIDATION_RUN')
    os.environ['SHIFTSTEAD_VALIDATION_RUN'] = run_id
    value = {'schema': 2, 'passed': False, 'status': 'running', 'stages': [],
             'source': source, 'run_id': run_id, 'source_changed': False, 'environment': environment()}
    atomic_json('results/validation.json', value)
    Path('results/report.html').write_text('<!doctype html><meta charset="utf-8"><h1>Validation in progress</h1><p>No current success result yet.</p>')
    try:
        for module, timeout in [('tools.test_suite', 180), ('tools.mutation_check', 180), ('tools.benchmark', 180), ('tools.report', 20)]:
            began = time.monotonic()
            code, timed_out, _, leaked = run_stage([sys.executable, '-m', module], timeout)
            changed = provenance() != source
            value['source_changed'] = changed
            value['stages'].append({'module': module, 'exit_code': code, 'timed_out': timed_out,
                                    'leaked_workers_cleaned': leaked, 'seconds': time.monotonic() - began})
            atomic_json('results/validation.json', value)
            if code or timed_out or leaked or changed:
                break
        value['passed'] = len(value['stages']) == 4 and not value['source_changed'] and all(
            s['exit_code'] == 0 and not s['timed_out'] and not s['leaked_workers_cleaned'] for s in value['stages'])
    except BaseException as e:
        value['error'] = type(e).__name__
        raise
    finally:
        if prior_run is None:
            os.environ.pop('SHIFTSTEAD_VALIDATION_RUN', None)
        else:
            os.environ['SHIFTSTEAD_VALIDATION_RUN'] = prior_run
        value['status'] = 'passed' if value['passed'] else 'failed'
        atomic_json('results/validation.json', value)
        if not value['passed']:
            Path('results/report.html').write_text('<!doctype html><meta charset="utf-8"><h1>Validation FAILED</h1><p>See <a href="validation.json">stage outcomes</a> and <a href="benchmark.json">raw trial records</a>. Older measurements do not constitute a successful current validation.</p>')
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
