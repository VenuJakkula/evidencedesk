"""Resolve installed runtime dependency closure into exact pins for Python 3.12 Linux.

Run after a clean install when intentionally updating dependencies. Does not include
development/learning extras or credential-bearing direct URLs.
"""
import tomllib
import argparse
from pathlib import Path
from importlib.metadata import distribution
from packaging.requirements import Requirement
from packaging.markers import default_environment
from packaging.utils import canonicalize_name


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--extras',default='')
    parser.add_argument('--output',default='requirements.lock')
    args=parser.parse_args()
    project=tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    pending=list(project['project']['dependencies']);seen={};expanded=set()
    for extra in filter(None,args.extras.split(',')):
        pending.extend(project['project']['optional-dependencies'][extra])
    target=default_environment()
    target.update(python_version='3.12',python_full_version='3.12.0',sys_platform='linux',
                  os_name='posix',platform_system='Linux',platform_machine='x86_64')
    while pending:
        request=Requirement(pending.pop())
        if request.url:raise ValueError('Direct URLs cannot enter the runtime lock')
        if request.marker and not any(request.marker.evaluate({**target,'extra':extra}) for extra in ['',*request.extras]):continue
        package=distribution(request.name)
        if package.version not in request.specifier:raise ValueError(f'Installed {request.name} violates declared requirement')
        name=canonicalize_name(package.metadata['Name'])
        seen[name]=package.version
        key=(name,tuple(sorted(request.extras)))
        if key in expanded:continue
        expanded.add(key)
        for dependency in package.requires or []:
            required=Requirement(dependency)
            if required.marker and not any(required.marker.evaluate({**target,'extra':extra}) for extra in ['',*request.extras]):continue
            required.marker=None
            pending.append(str(required))
    Path(args.output).write_text('# Python 3.12 Linux pins; extras: '+(args.extras or 'none')+'; regenerate with scripts.lock_runtime.\n'+
        '\n'.join(f'{name}=={value}' for name,value in sorted(seen.items()))+'\n',encoding='utf-8')
    print(f'Locked {len(seen)} dependencies in {args.output}; extras: {args.extras or "none"}.')

if __name__=='__main__':main()
