import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from certify_portals import _discover_public_portal


class PublicSourceIsolation(unittest.TestCase):
    def test_failed_board_does_not_prevent_next_board(self):
        with tempfile.TemporaryDirectory() as root:
            config=Path(root)/'sources.json'
            config.write_text(json.dumps({'greenhouse_boards':['failed','healthy']}))
            with patch('certify_portals.discover_greenhouse',side_effect=[TimeoutError(),['fixture-job']]) as discover:
                jobs, failures=_discover_public_portal('greenhouse',str(config),())
        self.assertEqual(discover.call_count,2)
        self.assertEqual(jobs,['fixture-job'])
        self.assertEqual(failures,[{'reason_code':'TimeoutError'}])

    def test_lever_discovery_does_not_repeat_failed_greenhouse_boards(self):
        with tempfile.TemporaryDirectory() as root:
            config=Path(root)/'sources.json'
            config.write_text(json.dumps({'greenhouse_boards':['failed'],'lever_sites':['healthy']}))
            with patch('certify_portals.discover_greenhouse',side_effect=AssertionError('wrong portal')) as greenhouse, \
                 patch('certify_portals.discover_lever',return_value=['fixture-job']):
                jobs, failures=_discover_public_portal('lever',str(config),())
        greenhouse.assert_not_called()
        self.assertEqual(jobs,['fixture-job'])
        self.assertEqual(failures,[])
