"""Check parser, report and process-runner output as separate boundaries."""
import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from importroute import __main__ as cli


class DeliveryTests(unittest.TestCase):
    def test_parser_destinations_and_stream_failures(self):
        for arguments in (['--help'], [], ['--unknown']):
            for destination in ('stdout', 'stderr'):
                for failure in ('write', 'flush', 'short', 'closed', 'none'):
                    with self.subTest(arguments=arguments, destination=destination, failure=failure):
                        class Stream(io.StringIO):
                            def write(self, text):
                                if failure == 'write':
                                    raise OSError('write failed')
                                if failure == 'short':
                                    return 0
                                return super().write(text)

                            def flush(self):
                                if failure == 'flush':
                                    raise OSError('flush failed')
                                return super().flush()

                        target = Stream()
                        if failure == 'closed':
                            target.close()
                        if failure == 'none':
                            target = None
                        output, error = io.StringIO(), io.StringIO()
                        if destination == 'stdout':
                            output = target
                        else:
                            error = target
                        with patch.object(sys, 'stdout', output), patch.object(sys, 'stderr', error):
                            affected = destination == ('stdout' if arguments == ['--help'] else 'stderr')
                            if affected:
                                self.assertEqual(cli.main(arguments), 2)
                            else:
                                with self.assertRaises(SystemExit) as raised:
                                    cli.main(arguments)
                                self.assertEqual(raised.exception.code, 0 if arguments == ['--help'] else 2)
                            self.assertIs(sys.stdout, output)
                            self.assertIs(sys.stderr, error)

    def test_report_requires_integer_complete_write(self):
        for accepted in (0, 1, None, True, -1, 'all'):
            for arguments in (['missingprobe', '--path', '/missing/root'],
                              ['../invalid', '--path', '/missing/root', '--json']):
                with self.subTest(accepted=accepted, arguments=arguments):
                    class Stream(io.StringIO):
                        def write(self, text):
                            super().write(text[:1])
                            return accepted
                    output = Stream()
                    with contextlib.redirect_stdout(output):
                        self.assertEqual(cli.main(arguments), 2)
                        self.assertIs(sys.stdout, output)
                        self.assertFalse(output.closed)

    def test_process_parser_failure(self):
        for arguments in (['--help'], [], ['--unknown']):
            destination = 'stdout' if arguments == ['--help'] else 'stderr'
            other = 'stderr' if destination == 'stdout' else 'stdout'
            for sink in ('full', 'pipe'):
                with self.subTest(arguments=arguments, sink=sink):
                    if sink == 'full':
                        if not Path('/dev/full').exists():
                            continue
                        with open('/dev/full', 'wb') as target:
                            result = subprocess.run([sys.executable, '-m', 'importroute'] + arguments,
                                                    **{destination: target, other: subprocess.PIPE},
                                                    timeout=10)
                    else:
                        read_fd, write_fd = os.pipe()
                        os.close(read_fd)
                        try:
                            result = subprocess.run([sys.executable, '-m', 'importroute'] + arguments,
                                                    **{destination: write_fd, other: subprocess.PIPE},
                                                    timeout=10)
                        finally:
                            os.close(write_fd)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(getattr(result, other), b'')

    def test_runner_late_flush_and_systemexit(self):
        for name in ('stdout', 'stderr'):
            for result in ((0, False), SystemExit(0), SystemExit(2)):
                with self.subTest(name=name, result=result):
                    class Stream(io.StringIO):
                        def flush(self):
                            raise OSError('late failure')
                    target = Stream()
                    options = ({'side_effect': result} if isinstance(result, SystemExit)
                               else {'return_value': result})
                    with patch.object(sys, name, target), patch.object(cli, '_run', **options):
                        self.assertEqual(cli.entrypoint(), 2)
                        self.assertIsNone(getattr(sys, name))
                        self.assertFalse(target.closed)

    def test_unexpected_trace_defect_propagates(self):
        with patch.object(cli, 'trace_imports', side_effect=AttributeError('internal defect')):
            with self.assertRaisesRegex(AttributeError, 'internal defect'):
                cli.main(['missingprobe', '--path', '/missing/root'])

    def test_normal_parser_exits_and_no_unwanted_output(self):
        for arguments in (['--help'], [], ['--unknown']):
            output, error = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(arguments)
            self.assertEqual(raised.exception.code, 0 if arguments == ['--help'] else 2)
            self.assertTrue(output.getvalue() if arguments == ['--help'] else error.getvalue())
            self.assertFalse(error.getvalue() if arguments == ['--help'] else output.getvalue())


if __name__ == '__main__':
    unittest.main()
