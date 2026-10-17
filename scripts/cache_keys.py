#!/usr/bin/env python3
"""Cache compiled tools and shaders by their inputs, independently of the app release."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import ci


def fingerprint(files, values):
    h = hashlib.sha256(json.dumps(values, sort_keys=True).encode())
    for name, path in sorted(files.items()):
        h.update(name.encode() + b'\0' + path.read_bytes() + b'\0')
    return h.hexdigest()


def keys(upstream, config, sdk, chain=None):
    upstream = Path(upstream)
    tools = fingerprint({'tools.sh': ci.ROOT / 'scripts/tools.sh'},
                        {k: config[k] for k in ('spirv_commit', 'hactool_commit')})
    chain_source = upstream / 'dm/gfx/tools/dmsh_chain.py'
    tree = ast.parse(chain_source.read_text())
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'FILES' for t in n.targets)]
    if len(assignments) != 1:
        raise ValueError('Cannot determine upstream shader dependencies')
    dependencies = ast.literal_eval(assignments[0].value)
    files = {}
    for name in dependencies:
        path = (upstream / 'dm/gfx' / name).resolve()
        files[str(path.relative_to(upstream.resolve()))] = path
    for name in ('dm/gfx/tools/nometal_run.py', 'dm/tools/dmx.py'):
        files[name] = upstream / name
    for path in (upstream / 'dm/third_party/ryujinx').rglob('*'):
        if path.is_file() and not any(p in ('bin', 'obj', '.git', '__pycache__') for p in path.parts):
            files[str(path.relative_to(upstream))] = path
    shaders = fingerprint(files, {'spirv': config['spirv_commit'], 'sdk': sdk,
                                  'game': config['game_version'], 'switch': config['switch_version'],
                                  'nso': config['nso_sha256'], 'mode': 'no-metal',
                                  'inputs': os.environ.get('INPUT_REVISION', ''), 'verified_chain': chain})
    return {'tools': tools, 'shaders': shaders}


if __name__ == '__main__':
    sdk = subprocess.check_output(['dotnet', '--version'], text=True).strip()
    upstream = ci.ROOT / 'upstream'
    chain = None
    if sys.argv[1:] == ['shaders']:
        chain = subprocess.check_output([sys.executable, str(upstream / 'dm/gfx/tools/nometal_run.py'),
                                         str(upstream / 'dm/gfx/tools/dmsh_chain.py')], text=True).strip().splitlines()[-1]
    result = keys(upstream, ci.CONFIG, sdk, chain)
    for key, value in result.items():
        print(key + '=' + value)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in result.items()))
