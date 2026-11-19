"""Offline integration and workflow wiring regressions for publication."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'macro-backtest/persist_results.py'
BRANCH = 'macro-backtest-v08'


def run(work, *args):
    return subprocess.check_output(args, cwd=work, text=True, stderr=subprocess.STDOUT).strip()


class Writers(unittest.TestCase):
    def test_queue_and_dependencies(self):
        workflows = ROOT / '.github/workflows'
        writers = 0
        for file in workflows.glob('*.yml'):
            data = yaml.load(file.read_text(), Loader=yaml.BaseLoader)
            if data.get('permissions', {}).get('contents') != 'write':
                continue
            writers += 1
            self.assertEqual(data['concurrency'], {'group': 'macro-backtest-v08-results-writer',
                                                   'queue': 'max', 'cancel-in-progress': 'false'})
            self.assertIn('persist_results.py', str(data['jobs']))
        self.assertEqual(writers, 7)
        orchestration = workflows / 'macro-orchestration-split-test.yml'
        paths = yaml.load(orchestration.read_text(), Loader=yaml.BaseLoader)['on']['push']['paths']
        pending = [ROOT / 'macro-backtest/orchestration_split_test.py']
        checked = set()
        while pending:
            script = pending.pop()
            if script in checked:
                continue
            checked.add(script)
            self.assertIn(script.relative_to(ROOT).as_posix(), paths)
            for node in ast.walk(ast.parse(script.read_text())):
                names = ([n.name for n in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    dep = script.with_name(name.split('.')[0] + '.py')
                    if dep.is_file():
                        pending.append(dep)

    def test_siblings_and_stale_source(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            remote = folder / 'repo.git'
            seed = folder / 'seed'
            run(folder, 'git', 'init', '--bare', '-b', BRANCH, str(remote))
            run(folder, 'git', 'clone', str(remote), str(seed))
            run(seed, 'git', 'config', 'user.name', 'Fixture')
            run(seed, 'git', 'config', 'user.email', 'fixture@example.invalid')
            (seed / 'engine').write_text('original')
            run(seed, 'git', 'add', 'engine')
            run(seed, 'git', 'commit', '-m', 'initial')
            run(seed, 'git', 'push', 'origin', BRANCH)
            base = run(seed, 'git', 'rev-parse', 'HEAD')
            env = dict(os.environ, GITHUB_REF_NAME=BRANCH)
            bundle = 'macro-backtest/results-provenance/123-1/defense'
            for name, outputs in [('alpha', ['macro-backtest/results', bundle]),
                                  ('bravo', ['macro-backtest/results-other']),
                                  ('charlie', ['macro-backtest/results'])]:
                work = folder / name
                run(folder, 'git', 'clone', str(remote), str(work))
                run(work, 'git', 'checkout', '--detach', base)
                for out in outputs:
                    (work / out).mkdir(parents=True, exist_ok=True)
                    (work / out / 'report').write_text(name)
                subprocess.run([sys.executable, HELPER, *outputs, name], env=env,
                               cwd=work, check=True, capture_output=True)
            for out, value in [('macro-backtest/results', 'charlie'),
                               ('macro-backtest/results-other', 'bravo'), (bundle, 'alpha')]:
                self.assertEqual(run(remote, 'git', 'show', f'{BRANCH}:{out}/report'), value)
            run(seed, 'git', 'pull', '--ff-only')
            (seed / 'engine').write_text('new code')
            run(seed, 'git', 'commit', '-am', 'advance source')
            run(seed, 'git', 'push', 'origin', BRANCH)
            failed = subprocess.run([sys.executable, HELPER, 'macro-backtest/results', 'stale'],
                                    env=env, cwd=work, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('Source changed after checkout', failed.stderr)


if __name__ == '__main__':
    unittest.main()
