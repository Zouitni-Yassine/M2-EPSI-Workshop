"""Package only explicitly listed Red Team sources; never include local secrets."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCES = (
    '.gitignore', 'README.md', 'Lancer-RedTeam.cmd', 'run.py', 'run-waf.ps1',
    'scope.example.json', 'ssh_relay.py', 'requirements-relay.txt',
    'tests/test_guardrails.py', 'package.py',
)


def package(output):
    output = Path(output)
    content = {name: (ROOT / name).read_bytes() for name in SOURCES}
    manifest = {'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'files_sha256': {name: hashlib.sha256(data).hexdigest()
                                 for name, data in content.items()}}
    # Exclusive creation avoids overwriting an existing deliverable.
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in content.items():
            archive.writestr('redteam/' + name, data)
        archive.writestr('redteam/SOURCE-MANIFEST.json', json.dumps(manifest, indent=2))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('Code-RedTeam.zip'))
    print(package(parser.parse_args().output).resolve())
