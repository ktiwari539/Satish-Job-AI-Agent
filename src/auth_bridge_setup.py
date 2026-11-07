"""Configure the private bridge connection without exposing its shared key."""
import getpass
import json
import os
from pathlib import Path
from auth_bridge import AuthProvider


def main():
    target=Path('data/auth_bridge.json')
    endpoint=input('Apps Script deployment URL: ').strip()
    key=getpass.getpass('Bridge shared key (hidden, at least 32 characters): ')
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.tmp')
    try:
        fd=os.open(str(temporary),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        os.chmod(temporary,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump({'endpoint':endpoint,'shared_key':key},stream)
        AuthProvider(str(temporary))
        temporary.replace(target)
        print('Bridge connection saved locally. No credentials or mailbox messages were requested.')
        return 0
    except ValueError:
        print('Bridge configuration invalid; existing configuration retained.')
        return 2
    finally:
        temporary.unlink(missing_ok=True)


if __name__=='__main__':
    raise SystemExit(main())
