"""退款对账的持久化、冻结、应用与导出。

流程状态：pending_analysis -> pending_apply -> applied。
分析时把窗口内班级日事实整体冻结到 basis，之后的应用只认这份 basis；
应用前重新读取日报指纹，一旦与 basis 不同就整单拒绝并退回待分析。
应用在一个事务内完成，进程中断只会回滚，不会留下半单更正。
"""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException

from src.models.entities import Audit, Fact, Reconciliation
from src.services import reconcile
from src.services.business import audit, dump

PENDING_ANALYSIS = 'pending_analysis'
PENDING_APPLY = 'pending_apply'
APPLIED = 'applied'


def _now():
    return datetime.now(timezone.utc).isoformat()


def _spec(data):
    """把请求模型转为可 JSON 化的约束描述。"""
    values = data.model_dump(mode='json')
    return {
        'class_code': values['class_code'],
        'date_from': values['date_from'],
        'date_to': values['date_to'],
        'intervals': [
            {
                'date_from': iv['date_from'],
                'date_to': iv['date_to'],
                'total': int(iv['total']),
                'label': iv.get('label', ''),
            }
            for iv in values['intervals']
        ],
        'verified': {d: int(v) for d, v in sorted(values['verified'].items())},
    }


def _window(spec):
    return reconcile.day_range(spec['date_from'], spec['date_to'])


def _facts_for(s, class_code, days):
    rows = (
        s.query(Fact)
        .filter(Fact.class_code == class_code, Fact.day.in_(days))
        .order_by(Fact.day)
        .all()
    )
    by_day = {row.day: row for row in rows}
    missing = [d for d in days if d not in by_day]
    if missing:
        raise HTTPException(409, '窗口内缺少班级日事实：%s，请先补齐日报再分析' % '、'.join(missing))
    return [dump(by_day[d]) for d in days]


def build_basis(s, spec):
    """读取当前日报并冻结为分析依据。"""
    days = _window(spec)
    rows = _facts_for(s, spec['class_code'], days)
    caps = {row['day']: int(row['enrolled']) for row in rows}
    basis = {
        'class_code': spec['class_code'],
        'date_from': spec['date_from'],
        'date_to': spec['date_to'],
        'days': days,
        'caps': caps,
        'facts': rows,
        'facts_checksum': reconcile.facts_fingerprint(rows),
        'frozen_at': _now(),
    }
    basis['inputs_checksum'] = reconcile.inputs_checksum(
        days, caps, spec['intervals'], spec['verified']
    )
    return basis


def _basis_args(basis, spec):
    return basis['days'], basis['caps'], spec['intervals'], spec['verified']


def create(s, data, actor):
    spec = _spec(data)
    record = Reconciliation(
        class_code=spec['class_code'],
        date_from=spec['date_from'],
        date_to=spec['date_to'],
        state=PENDING_ANALYSIS,
        constraint_spec=spec,
        basis=None,
        analysis=None,
        correction=None,
        created_by=actor.email,
        created=_now(),
    )
    s.add(record)
    s.commit()
    audit(s, actor, '建立退款对账 %s / %s ~ %s' % (record.class_code, record.date_from, record.date_to))
    return record


def update(s, record, data, actor):
    if record.state == APPLIED:
        raise HTTPException(409, '对账已应用，历史记录不可改写；请新建一份对账')
    record.constraint_spec = _spec(data)
    record.class_code = record.constraint_spec['class_code']
    record.date_from = record.constraint_spec['date_from']
    record.date_to = record.constraint_spec['date_to']
    # 约束变了，旧分析与冻结依据作废，必须重新分析。
    record.basis = None
    record.analysis = None
    record.correction = None
    record.state = PENDING_ANALYSIS
    record.analyzed_by = ''
    record.analyzed_at = ''
    s.commit()
    audit(s, actor, '修订退款对账约束 %s，分析作废待重算' % record.id)
    return record


def analyze(s, record, actor):
    if record.state == APPLIED:
        raise HTTPException(409, '对账已应用，不能重新分析；历史签核与更正依据保持不变')
    spec = record.constraint_spec or {}
    basis = build_basis(s, spec)
    days, caps, intervals, verified = _basis_args(basis, spec)
    result = reconcile.analyze(days, caps, intervals, verified)
    record.basis = basis
    record.analysis = result
    record.analyzed_by = actor.email
    record.analyzed_at = _now()
    record.state = PENDING_APPLY if result['status'] == 'unique' else PENDING_ANALYSIS
    s.commit()
    audit(s, actor, '分析退款对账 %s：%s' % (
        record.id,
        {'unique': '唯一解', 'multiple': '多解', 'conflict': '无解'}[result['status']],
    ))
    return record


def _reject_stale(s, record, reason):
    """整单拒绝：退回待分析，保留被拒依据供页面与审计查看。"""
    record.state = PENDING_ANALYSIS
    record.analysis = {
        **(record.analysis or {}),
        'stale': True,
        'stale_reason': reason,
        'stale_detected_at': _now(),
    }
    s.commit()


def apply(s, record, actor):
    # 独占对账记录：并发重试只会有一个真正改写日报，另一个在锁释放后看到
    # APPLIED 并作为幂等重试返回，不会重复更正。
    record = (
        s.query(Reconciliation)
        .filter(Reconciliation.id == record.id)
        .with_for_update()
        .one()
    )
    if record.state == APPLIED:
        # 幂等重试：不再改写日报，也不重复记审计。
        return record, False
    if record.state != PENDING_APPLY or not record.analysis or record.analysis.get('status') != 'unique':
        raise HTTPException(409, '仅唯一解的待应用对账可以应用')

    basis = record.basis or {}
    spec = record.constraint_spec or {}
    days = basis['days']
    current_rows = _facts_for(s, spec['class_code'], days)
    current_checksum = reconcile.facts_fingerprint(current_rows)
    if current_checksum != basis['facts_checksum']:
        _reject_stale(s, record, '日报在分析后发生变化，请基于最新日报重算')
        raise HTTPException(409, '日报在分析后已变化，整单拒绝应用，请重新分析')

    solution = record.analysis['solution']
    problems = reconcile.validate_solution(
        days, basis['caps'], spec['intervals'], spec['verified'], solution
    )
    if problems:
        _reject_stale(s, record, '冻结解不再满足当前约束，请重新分析')
        raise HTTPException(409, '冻结解与约束不一致，整单拒绝应用，请重新分析')

    # 锁定当前日报行，避免应用过程中被事实修订穿插。
    locked = (
        s.query(Fact)
        .filter(Fact.class_code == spec['class_code'], Fact.day.in_(days))
        .with_for_update()
        .order_by(Fact.day)
        .all()
    )
    locked_checksum = reconcile.facts_fingerprint([dump(row) for row in locked])
    if locked_checksum != basis['facts_checksum']:
        _reject_stale(s, record, '日报在应用瞬间发生变化，请重新分析')
        raise HTTPException(409, '日报在应用时发生变化，整单拒绝应用，请重新分析')

    before = {row.day: int(row.refunds) for row in locked}
    changed = []
    for row in locked:
        target = int(solution[row.day])
        if row.refunds != target:
            row.refunds = target
            changed.append({'day': row.day, 'before': before[row.day], 'after': target})

    correction = {
        'solution': {d: int(solution[d]) for d in days},
        'days': [
            {
                'day': d,
                'before': before[d],
                'after': int(solution[d]),
                'changed': before[d] != int(solution[d]),
                'enrolled': int(basis['caps'][d]),
            }
            for d in days
        ],
        'changed_days': changed,
        'interval_totals': [
            {
                'date_from': iv['date_from'],
                'date_to': iv['date_to'],
                'total': int(iv['total']),
                'label': iv.get('label', ''),
            }
            for iv in spec['intervals']
        ],
        'verified': {d: int(v) for d, v in spec['verified'].items()},
        'basis_checksum': basis['facts_checksum'],
        'inputs_checksum': basis.get('inputs_checksum'),
        'constraints_checksum': _constraints_checksum(spec),
        'analysis_checksum': _analysis_checksum(record.analysis),
        'applied_by': actor.email,
        'applied_at': _now(),
        'rule_version': reconcile.RULE_VERSION,
    }
    record.correction = correction
    record.state = APPLIED
    record.applied_by = actor.email
    record.applied_at = correction['applied_at']
    # 日报更正、对账状态与审计在同一事务提交：中断整体回滚，不留下半单更正；
    # 成功后的重试在入口处按 APPLIED 直接返回，不重复改写。
    s.add(Audit(
        actor=actor.email,
        action='应用退款对账 %s，更正 %d 日' % (record.id, len(changed)),
        created=_now(),
    ))
    try:
        s.commit()
    except Exception:
        s.rollback()
        raise
    return record, True


def _constraints_checksum(spec):
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    ).hexdigest()


def _analysis_checksum(analysis):
    payload = {k: analysis.get(k) for k in ('status', 'solution', 'ranges', 'conflicts', 'rule_version', 'inputs_checksum')}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    ).hexdigest()


def export(record):
    analysis = record.analysis or {}
    basis = record.basis or {}
    return {
        'id': record.id,
        'class_code': record.class_code,
        'date_from': record.date_from,
        'date_to': record.date_to,
        'state': record.state,
        'rule_version': reconcile.RULE_VERSION,
        'method': reconcile.METHOD,
        'constraints': record.constraint_spec,
        'analysis': {
            'status': analysis.get('status'),
            'solution': analysis.get('solution'),
            'ranges': analysis.get('ranges', []),
            'conflicts': analysis.get('conflicts', []),
            'inputs_checksum': analysis.get('inputs_checksum'),
            'stale': bool(analysis.get('stale')),
            'stale_reason': analysis.get('stale_reason', ''),
        },
        # 分析依据固定：保留冻结时点的日报与指纹。
        'basis': {
            'facts': basis.get('facts', []),
            'caps': basis.get('caps', {}),
            'facts_checksum': basis.get('facts_checksum'),
            'inputs_checksum': basis.get('inputs_checksum'),
            'frozen_at': basis.get('frozen_at'),
        },
        'correction': record.correction,
        'created_by': record.created_by,
        'created': record.created,
        'analyzed_by': record.analyzed_by,
        'analyzed_at': record.analyzed_at,
        'applied_by': record.applied_by,
        'applied_at': record.applied_at,
    }
