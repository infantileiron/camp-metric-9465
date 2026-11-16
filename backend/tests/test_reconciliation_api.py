import os
import tempfile
import unittest
from pathlib import Path


class ApiFlowTests(unittest.TestCase):
    """端到端 API 流程（SQLite，单进程；验证状态机、冻结与原子应用）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db_path = Path(cls.tmp.name) / 'test.db'
        os.environ['DATABASE_URL'] = 'sqlite:///%s' % db_path
        os.environ['JWT_SECRET'] = 'test-secret-reconciliation'
        os.environ['SEED_DEMO'] = 'false'
        os.environ.setdefault('REDIS_URL', 'redis://127.0.0.1:6379/0')

        from fastapi.testclient import TestClient
        import src.main as main
        from src.config.database import Base, engine, Session
        from src.models.entities import User, Fact
        from src.utils.security import hash_password

        Base.metadata.create_all(engine)
        with Session() as s:
            for role in ('admin', 'analyst', 'viewer'):
                s.add(User(email='%s@test.local' % role, role=role,
                           password=hash_password('Demo123!')))
            # QH-01：11-10 ~ 11-15，报名均为 5
            for day, refunds in [
                ('2026-11-10', 1), ('2026-11-11', 2), ('2026-11-12', 0),
                ('2026-11-13', 2), ('2026-11-14', 1), ('2026-11-15', 1),
            ]:
                s.add(Fact(class_code='QH-01', day=day, mode='线上', enrolled=5,
                           attended=4, completed=3, refunds=refunds))
            s.commit()

        cls.client = TestClient(main.app)
        cls.tokens = {}
        for role in ('admin', 'analyst', 'viewer'):
            r = cls.client.post('/auth/login', json={
                'email': '%s@test.local' % role, 'password': 'Demo123!'})
            assert r.status_code == 200, r.text
            cls.tokens[role] = r.json()['token']

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self, role, method, path, body=None):
        headers = {'Authorization': 'Bearer ' + self.tokens[role]}
        if method == 'get':
            return self.client.get('/' + path, headers=headers)
        return self.client.request(method.upper(), '/' + path, json=body, headers=headers)

    def setUp(self):
        # 每个用例从同一份日报出发，避免应用后的更正影响后续用例。
        base = {
            '2026-11-10': 1, '2026-11-11': 2, '2026-11-12': 0,
            '2026-11-13': 2, '2026-11-14': 1, '2026-11-15': 1,
        }
        facts = self.call('analyst', 'get', 'facts').json()
        for fact in facts:
            body = dict(fact)
            body['refunds'] = base[fact['day']]
            body['note'] = ''
            body.pop('id', None)
            resp = self.call('analyst', 'put', 'facts/%d' % fact['id'], body)
            self.assertEqual(resp.status_code, 200, resp.text)

    def unique_payload(self):
        # 6 日、每日最多 5；区间 10-12=5、12-15=5、10-15=6，
        # 核实 11 日=1、13 日=0、14 日=0 ⇒ 逐日 0,1,4,0,0,1。
        return {
            'class_code': 'QH-01',
            'date_from': '2026-11-10',
            'date_to': '2026-11-15',
            'intervals': [
                {'date_from': '2026-11-10', 'date_to': '2026-11-12', 'total': 5, 'label': '上半周'},
                {'date_from': '2026-11-12', 'date_to': '2026-11-15', 'total': 5, 'label': '下半周'},
                {'date_from': '2026-11-10', 'date_to': '2026-11-15', 'total': 6, 'label': '全周'},
            ],
            'verified': {'2026-11-11': 1, '2026-11-13': 0, '2026-11-14': 0},
        }

    def test_full_flow_unique_apply_and_idempotent_retry(self):
        created = self.call('analyst', 'post', 'reconciliations', self.unique_payload())
        self.assertEqual(created.status_code, 200, created.text)
        record = created.json()
        self.assertEqual(record['state'], 'pending_analysis')
        rid = record['id']

        analyzed = self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {})
        self.assertEqual(analyzed.status_code, 200, analyzed.text)
        analyzed = analyzed.json()
        self.assertEqual(analyzed['analysis']['status'], 'unique', analyzed['analysis'])
        self.assertEqual(analyzed['state'], 'pending_apply')

        # viewer 不能应用
        self.assertEqual(self.call('viewer', 'post', 'reconciliations/%d/apply' % rid, {}).status_code, 403)

        applied = self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {})
        self.assertEqual(applied.status_code, 200, applied.text)
        applied = applied.json()
        self.assertTrue(applied['changed'])
        self.assertEqual(applied['state'], 'applied')
        correction = {d['day']: d['after'] for d in applied['correction']['days']}
        self.assertEqual(
            correction,
            {'2026-11-10': 0, '2026-11-11': 1, '2026-11-12': 4,
             '2026-11-13': 0, '2026-11-14': 0, '2026-11-15': 1},
        )

        facts = self.call('admin', 'get', 'facts').json()
        self.assertEqual({f['day']: f['refunds'] for f in facts},
                         correction)

        # 幂等重试：不改日报、不重复记审计
        audits_before = len(self.call('admin', 'get', 'audits').json())
        again = self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertFalse(again.json()['changed'])
        facts_again = self.call('admin', 'get', 'facts').json()
        self.assertEqual({f['day']: f['refunds'] for f in facts_again}, correction)
        self.assertEqual(len(self.call('admin', 'get', 'audits').json()), audits_before)

    def test_multiple_solution_cannot_apply(self):
        payload = self.unique_payload()
        payload['intervals'] = [{'date_from': '2026-11-10', 'date_to': '2026-11-15', 'total': 6}]
        payload['verified'] = {}
        rid = self.call('analyst', 'post', 'reconciliations', payload).json()['id']
        out = self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {})
        self.assertEqual(out.status_code, 200, out.text)
        out = out.json()
        self.assertEqual(out['analysis']['status'], 'multiple')
        self.assertEqual(out['state'], 'pending_analysis')
        self.assertTrue(all('min' in r and 'max' in r for r in out['analysis']['ranges']))
        denied = self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {})
        self.assertEqual(denied.status_code, 409)

    def test_conflict_lists_conflicting_intervals(self):
        payload = self.unique_payload()
        payload['intervals'] = [
            {'date_from': '2026-11-10', 'date_to': '2026-11-10', 'total': 4},
            {'date_from': '2026-11-11', 'date_to': '2026-11-15', 'total': 3},
            {'date_from': '2026-11-10', 'date_to': '2026-11-15', 'total': 5},
        ]
        payload['verified'] = {}
        rid = self.call('analyst', 'post', 'reconciliations', payload).json()['id']
        out = self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {}).json()
        self.assertEqual(out['analysis']['status'], 'conflict')
        conflicts = out['analysis']['conflicts']
        self.assertTrue(conflicts)
        self.assertTrue(any(c['kind'] == 'interval' for c in conflicts))
        self.assertEqual(self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {}).status_code, 200)

    def test_stale_daily_facts_reject_whole_apply(self):
        rid = self.call('analyst', 'post', 'reconciliations', self.unique_payload()).json()['id']
        self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {})
        facts = self.call('analyst', 'get', 'facts').json()
        target = next(f for f in facts if f['day'] == '2026-11-13')
        changed = dict(target)
        changed['refunds'] = 1
        changed['note'] = '并发更正'
        changed.pop('id', None)
        resp = self.call('analyst', 'put', 'facts/%d' % target['id'], changed)
        self.assertEqual(resp.status_code, 200, resp.text)

        before = {f['day']: f['refunds'] for f in self.call('analyst', 'get', 'facts').json()}
        denied = self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {})
        self.assertEqual(denied.status_code, 409, denied.text)
        after = {f['day']: f['refunds'] for f in self.call('analyst', 'get', 'facts').json()}
        self.assertEqual(before, after)
        record = self.call('analyst', 'get', 'reconciliations/%d' % rid).json()
        self.assertEqual(record['state'], 'pending_analysis')
        self.assertTrue(record['analysis']['stale'])

    def test_edit_after_apply_rejected_and_analysis_refrozen(self):
        rid = self.call('analyst', 'post', 'reconciliations', self.unique_payload()).json()['id']
        self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {})
        self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {})
        payload = self.unique_payload()
        payload['date_to'] = '2026-11-15'
        self.assertEqual(
            self.call('analyst', 'put', 'reconciliations/%d' % rid, payload).status_code, 409)
        # 已应用记录重新分析也被拒绝，历史不变
        self.assertEqual(
            self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {}).status_code, 409)

    def test_export_keeps_constraints_solution_and_basis(self):
        rid = self.call('analyst', 'post', 'reconciliations', self.unique_payload()).json()['id']
        self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {})
        exported = self.call('viewer', 'get', 'reconciliations/%d/export' % rid)
        self.assertEqual(exported.status_code, 200)
        body = exported.json()
        self.assertEqual(body['constraints']['class_code'], 'QH-01')
        self.assertEqual(body['analysis']['status'], 'unique')
        self.assertEqual(len(body['basis']['facts']), 6)
        self.assertTrue(body['basis']['facts_checksum'])
        self.assertIn('correction', body)

    def test_viewer_cannot_write(self):
        self.assertEqual(
            self.call('viewer', 'post', 'reconciliations', self.unique_payload()).status_code, 403)

    def test_interrupted_apply_rolls_back_and_retry_succeeds(self):
        from unittest.mock import patch

        rid = self.call('analyst', 'post', 'reconciliations', self.unique_payload()).json()['id']
        self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {})
        before = {f['day']: f['refunds'] for f in self.call('analyst', 'get', 'facts').json()}

        from sqlalchemy.orm import Session as OrmSession
        with patch.object(OrmSession, 'commit', side_effect=RuntimeError('模拟进程中断')):
            with self.assertRaises(RuntimeError):
                self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {})

        # 中断后日报没有半单更正，记录仍停在待应用
        after = {f['day']: f['refunds'] for f in self.call('analyst', 'get', 'facts').json()}
        self.assertEqual(before, after)
        record = self.call('analyst', 'get', 'reconciliations/%d' % rid).json()
        self.assertEqual(record['state'], 'pending_apply')

        # 重试成功并且只应用一次
        retry = self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {})
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertTrue(retry.json()['changed'])
        self.assertEqual(retry.json()['state'], 'applied')

    def test_applied_correction_does_not_change_historical_signoff(self):
        from src.config.database import Session
        from src.models.entities import Snapshot, Metric

        with Session() as s:
            metric = s.query(Metric).filter_by(code='refund', version=1).first()
            if not metric:
                metric = Metric(code='refund', version=1, name='退款占比',
                                numerator='refunds', denominator='enrolled',
                                numerator_mode='全部', denominator_mode='全部',
                                note='测试口径')
                s.add(metric)
                s.commit()
            snapshot = Snapshot(
                metric_id=metric.id, date_from='2026-11-10', date_to='2026-11-15',
                state='done', note='历史签核说明不少于八字',
                result={
                    'metric': {
                        'code': 'refund', 'version': 1, 'name': '退款占比',
                        'numerator': 'refunds', 'denominator': 'enrolled',
                        'numerator_mode': '全部', 'denominator_mode': '全部',
                    },
                    'value': 0.1, 'facts_checksum': 'frozen-checksum',
                },
            )
            s.add(snapshot)
            s.commit()
            sid = snapshot.id
            original = snapshot.result

        approved = self.call('admin', 'post', 'snapshots/%d/approve' % sid, {})
        self.assertEqual(approved.status_code, 200, approved.text)

        rid = self.call('analyst', 'post', 'reconciliations', self.unique_payload()).json()['id']
        self.call('analyst', 'post', 'reconciliations/%d/analyze' % rid, {})
        self.assertEqual(self.call('admin', 'post', 'reconciliations/%d/apply' % rid, {}).status_code, 200)

        signed = self.call('analyst', 'get', 'snapshots/%d' % sid).json()
        self.assertEqual(signed['result'], original)
        self.assertEqual(signed['approval'], 'approved')
        self.assertEqual(signed['note'], '历史签核说明不少于八字')

    def test_validation_rejects_window_over_31_days(self):
        payload = self.unique_payload()
        payload['date_from'] = '2026-10-01'
        payload['date_to'] = '2026-11-15'
        resp = self.call('analyst', 'post', 'reconciliations', payload)
        self.assertEqual(resp.status_code, 422)


if __name__ == '__main__':
    unittest.main(verbosity=2)
