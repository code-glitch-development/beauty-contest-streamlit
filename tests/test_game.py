import hashlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game import (API_DEFAULT, DEADLINE, REVEAL_OPEN, commitment, consensus,
                  csv_bytes, demo_data, fetch_table, parse_ts, submit, validate,
                  filter_leaderboard_reveals, leaderboard_consensus)

C_TIME = '2026-11-14T10:00:00Z'
R_TIME = '2026-11-16T10:00:00Z'


def commit(uid='A', n=20, nonce='secret', ts=C_TIME):
    return dict(uni_id=uid, commit=commitment(uid, n, nonce), timestamp_utc=ts)


def reveal(uid='A', n='20', nonce='secret', ts=R_TIME):
    return dict(uni_id=uid, number=n, nonce=nonce, timestamp_utc=ts)


class ConsensusTests(unittest.TestCase):
    def test_hash_exactly_matches_client(self):
        self.assertEqual(commitment('A', 20, 'secret'), hashlib.sha256(b'A|20|secret').hexdigest())

    def test_input_validation(self):
        self.assertEqual(validate(' A ', 0, ' x '), ('A', 0, 'x'))
        for uid, n, nonce in [('', 1, 'x'), ('A', 101, 'x'), ('A', 2.5, 'x'), ('A', True, 'x'), ('A', 1, ''), ('A|B', 2, 'x')]:
            with self.assertRaises(ValueError):
                validate(uid, n, nonce)

    def test_demo_target(self):
        result = consensus(*demo_data())
        self.assertEqual(result['count'], 5)
        self.assertEqual(result['average'], 28)
        self.assertAlmostEqual(result['target'], 56 / 3)
        self.assertEqual(result['winners'], ['STU-003'])

    def test_latest_reveal_does_not_fall_back(self):
        result = consensus([commit()], [reveal(), reveal(n='21', ts='2026-11-16T11:00:00Z')])
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['rows'][0]['Status'], 'Hash mismatch')

    def test_latest_prior_commit_does_not_fall_back(self):
        result = consensus([commit(), commit(n=30, ts='2026-11-15T10:00:00Z')], [reveal()])
        self.assertEqual(result['rows'][0]['Status'], 'Hash mismatch')

    def test_future_commit_is_not_used(self):
        result = consensus([commit(), commit(n=30, ts='2026-11-17T10:00:00Z')], [reveal()])
        self.assertEqual(result['count'], 1)
        self.assertEqual(consensus([commit(ts='2026-11-17T10:00:00Z')], [reveal()])['count'], 0)

    def test_timestamp_equal_uses_last_csv_row(self):
        self.assertEqual(consensus([commit(n=30), commit()], [reveal()])['count'], 1)
        self.assertEqual(consensus([commit()], [reveal(n='30'), reveal()])['count'], 1)

    def test_bad_timestamps_are_reported(self):
        result = consensus([commit(ts='invalid'), commit()], [reveal(ts='2026-11-16T12:00:00'), reveal()])
        self.assertEqual(len(result['issues']), 2)
        self.assertEqual(result['count'], 1)
        self.assertEqual(parse_ts('2026-11-16T11:00:00+01:00'), parse_ts(R_TIME))

    def test_rejected_values(self):
        for n, nonce, status in [('20.0', 'secret', 'Number is not an integer'), ('101', 'secret', 'Number is outside 0–100'), ('20', '', 'Missing nonce'), ('20', 'wrong', 'Hash mismatch')]:
            self.assertEqual(consensus([commit()], [reveal(n=n, nonce=nonce)])['rows'][0]['Status'], status)

    def test_numeric_order_and_tied_winners(self):
        commits = [commit('A', 10), commit('B', 30), commit('C', 50)]
        reveals = [reveal('A', '10'), reveal('B', '30'), reveal('C', '50')]
        result = consensus(commits, reveals)
        self.assertEqual(result['target'], 20)
        self.assertEqual(result['winners'], ['A', 'B'])
        self.assertEqual([r['Rank'] for r in result['rows']], [1, 1, 3])
        self.assertEqual([r['Distance'] for r in result['rows']], [10, 10, 30])

    def test_empty_and_csv(self):
        self.assertIsNone(consensus([], [])['target'])
        self.assertEqual(consensus([], [])['count'], 0)
        self.assertIn(b'University ID', csv_bytes([]))


class LeaderboardWindowTests(unittest.TestCase):
    def test_inclusive_paris_boundaries_and_utc_conversion(self):
        times = [
            '2026-11-16T11:59:59.999999Z',
            '2026-11-16T12:00:00Z',
            '2026-11-16T13:00:00+01:00',
            '2026-11-16T17:59:59+01:00',
            '2026-11-16T17:00:00Z',
            '2026-11-16T17:00:00.000001Z',
            '2025-11-16T14:00:00+01:00',
            '2026-11-15T14:00:00+01:00',
            '2026-11-17T14:00:00+01:00',
            'invalid',
            '2026-11-16T14:00:00',
        ]
        rows = [reveal(ts=ts) for ts in times]
        self.assertEqual([r['timestamp_utc'] for r in filter_leaderboard_reveals(rows)], times[1:5])

    def test_filter_precedes_latest_reveal_selection(self):
        rows = [reveal(n='99', ts='2026-11-16T11:00:00Z'),
                reveal(ts='2026-11-16T13:00:00Z'),
                reveal(n='80', ts='2026-11-16T17:00:01Z')]
        result = leaderboard_consensus([commit()], rows)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['rows'][0]['Number'], 20)

    def test_outside_players_do_not_affect_average_target_or_ranking(self):
        commits = [commit('A', 20), commit('B', 100)]
        rows = [reveal('A', '20', ts='2026-11-16T12:00:00Z'),
                reveal('B', '100', ts='2026-11-16T11:59:59Z')]
        result = leaderboard_consensus(commits, rows)
        self.assertEqual([r['University ID'] for r in result['rows']], ['A'])
        self.assertEqual(result['average'], 20)
        self.assertAlmostEqual(result['target'], 40 / 3)
        self.assertEqual(result['winners'], ['A'])

    def test_empty_window_and_commit_history_preserved(self):
        self.assertEqual(leaderboard_consensus([commit()], [reveal()])['count'], 0)
        result = leaderboard_consensus([commit(ts='2026-11-14T10:00:00Z')],
                                       [reveal(ts='2026-11-16T16:00:00Z')])
        self.assertEqual(result['count'], 1)
        self.assertEqual(leaderboard_consensus(*demo_data())['count'], 5)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.response = Mock()
        self.response.json.return_value = {'ok': True}
        self.http = SimpleNamespace(get=Mock(return_value=self.response), post=Mock(return_value=self.response))
        self.context = patch.dict(sys.modules, {'requests': self.http})
        self.context.start()
        self.addCleanup(self.context.stop)

    def test_no_post_outside_phase(self):
        for payload, now in [({'kind': 'commit'}, DEADLINE + timedelta(microseconds=1)), ({'kind': 'reveal'}, REVEAL_OPEN - timedelta(microseconds=1))]:
            with self.assertRaises(ValueError):
                submit(API_DEFAULT, payload, now)
        self.http.post.assert_not_called()

    def test_payload_and_boundary(self):
        payload = {'kind': 'commit', 'uni_id': 'A', 'commit': commitment('A', 20, 'secret')}
        self.assertEqual(submit(API_DEFAULT, payload, DEADLINE), 'confirmed')
        self.http.post.assert_called_once_with(API_DEFAULT, json=payload, timeout=20)
        self.assertEqual(submit(API_DEFAULT, {'kind': 'reveal'}, REVEAL_OPEN), 'confirmed')

    def test_server_rejection_and_unknown_ack(self):
        for body in [{'error': 'Closed'}, {'ok': False}, {'status': 'error'}]:
            self.response.json.return_value = body
            with self.assertRaises(ValueError):
                submit(API_DEFAULT, {'kind': 'commit'}, DEADLINE)
        self.response.json.return_value = {'message': 'Some response'}
        self.assertEqual(submit(API_DEFAULT, {'kind': 'commit'}, DEADLINE), 'unconfirmed')
        self.response.json.side_effect = ValueError('HTML')
        self.assertEqual(submit(API_DEFAULT, {'kind': 'commit'}, DEADLINE), 'unconfirmed')

    def test_valid_csv_and_html_detection(self):
        self.response.text = '\ufefftimestamp_utc,uni_id,commit\n2026-11-14T12:00:00Z,A,abc\n'
        self.assertEqual(fetch_table(API_DEFAULT, 'commits')[0]['uni_id'], 'A')
        self.response.text = '<html>Please log in</html>'
        with self.assertRaises(ValueError):
            fetch_table(API_DEFAULT, 'commits')

    def test_unsafe_or_wrong_endpoint(self):
        with self.assertRaises(ValueError):
            fetch_table('http://localhost/private', 'commits')
        self.http.get.assert_not_called()

    def test_network_error_is_not_retried(self):
        self.http.post.side_effect = TimeoutError('Timeout after write')
        with self.assertRaises(TimeoutError):
            submit(API_DEFAULT, {'kind': 'commit'}, DEADLINE)
        self.http.post.assert_called_once()


if __name__ == '__main__':
    unittest.main()
