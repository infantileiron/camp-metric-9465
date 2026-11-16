import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services import reconcile


def brute(days, caps, intervals, verified):
    """枚举所有满足约束的整数解，返回 (解集, 每日范围)。"""
    sols = []
    spans = [(days.index(iv['date_from']), days.index(iv['date_to']), iv['total']) for iv in intervals]
    for combo in itertools.product(*[range(caps[d] + 1) for d in days]):
        if any(combo[d] != v for d, v in verified.items() for d in [days.index(d)]):
            continue
        ok = True
        for a, b, total in spans:
            if sum(combo[a:b + 1]) != total:
                ok = False
                break
        if ok:
            sols.append(combo)
    return sols


class SolverTests(unittest.TestCase):
    def test_unique_solution(self):
        days = reconcile.day_range('2026-11-01', '2026-11-03')
        caps = {d: 5 for d in days}
        intervals = [
            {'date_from': days[0], 'date_to': days[1], 'total': 3},
            {'date_from': days[1], 'date_to': days[2], 'total': 4},
            {'date_from': days[0], 'date_to': days[2], 'total': 5},
        ]
        out = reconcile.analyze(days, caps, intervals, {})
        self.assertEqual(out['status'], 'unique')
        self.assertEqual(out['solution'], {days[0]: 1, days[1]: 2, days[2]: 2})

    def test_multiple_solution_reports_ranges(self):
        days = reconcile.day_range('2026-11-01', '2026-11-03')
        caps = {d: 5 for d in days}
        intervals = [{'date_from': days[0], 'date_to': days[2], 'total': 4}]
        out = reconcile.analyze(days, caps, intervals, {})
        self.assertEqual(out['status'], 'multiple')
        self.assertIsNone(out['solution'])
        ranges = {r['day']: (r['min'], r['max']) for r in out['ranges']}
        self.assertEqual(ranges[days[0]], (0, 4))
        self.assertEqual(ranges[days[2]], (0, 4))

    def test_verified_day_pins_range(self):
        days = reconcile.day_range('2026-11-01', '2026-11-03')
        caps = {d: 5 for d in days}
        intervals = [{'date_from': days[0], 'date_to': days[2], 'total': 4}]
        out = reconcile.analyze(days, caps, intervals, {days[1]: 1})
        self.assertEqual(out['status'], 'multiple')
        ranges = {r['day']: (r['min'], r['max']) for r in out['ranges']}
        self.assertEqual(ranges[days[1]], (1, 1))
        self.assertEqual(ranges[days[0]], (0, 3))

    def test_conflict_reports_intervals(self):
        days = reconcile.day_range('2026-11-01', '2026-11-03')
        caps = {d: 5 for d in days}
        intervals = [
            {'date_from': days[0], 'date_to': days[0], 'total': 4},
            {'date_from': days[1], 'date_to': days[2], 'total': 3},
            {'date_from': days[0], 'date_to': days[2], 'total': 5},
        ]
        out = reconcile.analyze(days, caps, intervals, {})
        self.assertEqual(out['status'], 'conflict')
        self.assertTrue(any(c['kind'] == 'interval' for c in out['conflicts']))

    def test_verified_conflict_reported(self):
        days = reconcile.day_range('2026-11-01', '2026-11-02')
        caps = {d: 5 for d in days}
        intervals = [{'date_from': days[0], 'date_to': days[1], 'total': 4}]
        out = reconcile.analyze(days, caps, intervals, {days[0]: 5})
        self.assertEqual(out['status'], 'conflict')
        kinds = {c['kind'] for c in out['conflicts']}
        self.assertIn('verified', kinds)

    def test_cap_conflict_reported(self):
        days = reconcile.day_range('2026-11-01', '2026-11-02')
        caps = {days[0]: 1, days[1]: 1}
        intervals = [{'date_from': days[0], 'date_to': days[1], 'total': 4}]
        out = reconcile.analyze(days, caps, intervals, {})
        self.assertEqual(out['status'], 'conflict')
        self.assertIn('daily_cap', {c['kind'] for c in out['conflicts']})

    def test_overlapping_intervals(self):
        days = reconcile.day_range('2026-11-01', '2026-11-05')
        caps = {d: 3 for d in days}
        intervals = [
            {'date_from': days[0], 'date_to': days[2], 'total': 4},
            {'date_from': days[2], 'date_to': days[4], 'total': 5},
            {'date_from': days[1], 'date_to': days[3], 'total': 3},
        ]
        out = reconcile.analyze(days, caps, intervals, {})
        sols = brute(days, caps, intervals, {})
        if sols:
            self.assertIn(out['status'], ('unique', 'multiple'))
            ranges = {r['day']: (r['min'], r['max']) for r in out['ranges']}
            for idx, d in enumerate(days):
                self.assertEqual(ranges[d], (min(s[idx] for s in sols), max(s[idx] for s in sols)))
        else:
            self.assertEqual(out['status'], 'conflict')

    def test_validation_rejects_bad_solution(self):
        days = reconcile.day_range('2026-11-01', '2026-11-02')
        caps = {d: 1 for d in days}
        intervals = [{'date_from': days[0], 'date_to': days[1], 'total': 1}]
        self.assertTrue(reconcile.validate_solution(days, caps, intervals, {}, {days[0]: 1, days[1]: 1}))
        self.assertFalse(reconcile.validate_solution(days, caps, intervals, {}, {days[0]: 1, days[1]: 0}))

    def test_random_cross_check(self):
        rng = random.Random(20261116)
        for _ in range(150):
            n = rng.randint(1, 4)
            days = reconcile.day_range('2026-11-01', '2026-11-%02d' % n)
            caps = {d: rng.randint(0, 2) for d in days}
            intervals = []
            for _ in range(rng.randint(1, 4)):
                a = rng.randint(0, n - 1)
                b = rng.randint(a, n - 1)
                intervals.append({
                    'date_from': days[a],
                    'date_to': days[b],
                    'total': rng.randint(0, 4),
                })
            verified = {}
            if rng.random() < 0.4:
                d = rng.choice(days)
                verified[d] = rng.randint(0, caps[d])
            out = reconcile.analyze(days, caps, intervals, verified)
            sols = brute(days, caps, intervals, verified)
            self.assertEqual(out['status'] == 'conflict', not sols)
            if sols:
                expected = 'unique' if all(
                    all(s[idx] == sols[0][idx] for s in sols) for idx in range(n)
                ) else 'multiple'
                self.assertEqual(out['status'], expected)
                ranges = {r['day']: (r['min'], r['max']) for r in out['ranges']}
                for idx, d in enumerate(days):
                    self.assertEqual(
                        ranges[d],
                        (min(s[idx] for s in sols), max(s[idx] for s in sols)),
                    )


if __name__ == '__main__':
    unittest.main(verbosity=1)
