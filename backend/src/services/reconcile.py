"""退款对账求解器。

财务按区间给出退款总人次，日报逐日退款常常对不上。这里把每个自然日的
退款人次作为非负整数变量 x[d]，联合满足：

* 每个区间内 x[d] 之和等于财务给出的区间总人次；
* 已核实日期 x[d] 等于核实值；
* 0 <= x[d] <= 当日报名人次。

区间总和约束可以写成前缀和之差，因此整个系统是差分约束系统（DBM）。
系数矩阵为网络矩阵，整数右端项下实数可行即整数可行；Floyd-Warshall
得到的整数最短路同时给出每个变量在所有整数解中的最小值和最大值。
最小值等于最大值时该日被唯一确定。

本模块只依赖标准库，便于单独测试。
"""
import hashlib
import json
from datetime import date, timedelta

RULE_VERSION = 'refund-reconcile-v1'
INF = 10 ** 18

METHOD = (
    '以窗口内每个自然日的退款人次为非负整数变量；把区间总额写成前缀和之差，'
    '连同核实日等式和逐日退款≤报名一起构成差分约束系统。Floyd-Warshall 求'
    '最短路闭包：负环表示无解，最短路给出各日整数可行范围；所有日期上下界'
    '相等时才视为唯一解。分析依据在提交时冻结，应用前再次核对日报。'
)


def day_range(date_from, date_to):
    """返回闭区间内的 ISO 日期列表。日期参数可为 date 或 ISO 字符串。"""
    a = date_from if isinstance(date_from, date) else date.fromisoformat(date_from)
    b = date_to if isinstance(date_to, date) else date.fromisoformat(date_to)
    if b < a:
        raise ValueError('开始日不得晚于结束日')
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def facts_fingerprint(rows):
    """日报事实的规范化指纹。

    纳入业务字段与更正说明；窗口内任一班级日事实变化都会改变指纹，
    应用前据此拒绝并发改写。分析本身不读取指纹之外的实时数据。
    """
    canonical = []
    for row in sorted(rows, key=lambda r: r['day']):
        canonical.append({
            'id': row.get('id'),
            'class_code': row.get('class_code'),
            'day': row['day'],
            'mode': row.get('mode'),
            'enrolled': row.get('enrolled'),
            'attended': row.get('attended'),
            'completed': row.get('completed'),
            'refunds': row.get('refunds'),
            'note': row.get('note') or '',
        })
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    ).hexdigest()


def inputs_checksum(days, caps, intervals, verified):
    payload = {
        'days': list(days),
        'caps': {d: int(caps[d]) for d in days},
        'intervals': [
            {
                'date_from': iv['date_from'],
                'date_to': iv['date_to'],
                'total': int(iv['total']),
                'label': iv.get('label', ''),
            }
            for iv in intervals
        ],
        'verified': {d: int(verified[d]) for d in sorted(verified)},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    ).hexdigest()


def _build_matrix(n, groups):
    dist = [[INF] * (n + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dist[i][i] = 0
    for group in groups:
        for u, v, w in group['edges']:
            if w < dist[u][v]:
                dist[u][v] = w
    return dist


def _floyd(dist):
    n = len(dist)
    for k in range(n):
        dk = dist[k]
        for i in range(n):
            dik = dist[i][k]
            if dik == INF:
                continue
            di = dist[i]
            for j in range(n):
                nd = dik + dk[j]
                if nd < di[j]:
                    di[j] = nd
    return dist


def _closure(n, groups):
    dist = _floyd(_build_matrix(n, groups))
    feasible = all(dist[i][i] >= 0 for i in range(n + 1))
    return feasible, dist


def _groups_for(days, caps, intervals, verified):
    index = {d: i + 1 for i, d in enumerate(days)}
    groups = []
    for d in days:
        i = index[d]
        cap = int(caps[d])
        groups.append({
            'kind': 'daily_cap',
            'day': d,
            'enrolled': cap,
            'edges': [(i - 1, i, cap), (i, i - 1, 0)],
        })
    for d in sorted(verified):
        i = index[d]
        value = int(verified[d])
        groups.append({
            'kind': 'verified',
            'day': d,
            'refunds': value,
            'edges': [(i - 1, i, value), (i, i - 1, -value)],
        })
    for k, iv in enumerate(intervals):
        a = index[iv['date_from']]
        b = index[iv['date_to']]
        total = int(iv['total'])
        groups.append({
            'kind': 'interval',
            'index': k,
            'date_from': iv['date_from'],
            'date_to': iv['date_to'],
            'total': total,
            'label': iv.get('label', ''),
            'edges': [(a - 1, b, total), (b, a - 1, -total)],
        })
    return groups, index


def _minimal_conflict(n, groups):
    """删除过滤求一个不可满足核心（IIS），用于列出冲突项。"""
    active = list(groups)
    for group in list(groups):
        trial = [g for g in active if g is not group]
        feasible, _ = _closure(n, trial)
        if not feasible:
            active = trial
    return active


def _conflicts(core):
    intervals = []
    verified = []
    caps = []
    for group in core:
        if group['kind'] == 'interval':
            intervals.append({
                'kind': 'interval',
                'index': group['index'],
                'date_from': group['date_from'],
                'date_to': group['date_to'],
                'total': group['total'],
                'label': group['label'],
                'message': '区间 %s ~ %s 合计 %s 与核实日或其它区间无法同时满足' % (
                    group['date_from'], group['date_to'], group['total']),
            })
        elif group['kind'] == 'verified':
            verified.append({
                'kind': 'verified',
                'day': group['day'],
                'refunds': group['refunds'],
                'message': '核实日 %s 的退款 %s 与区间总额或报名上限冲突' % (
                    group['day'], group['refunds']),
            })
        else:
            caps.append({'day': group['day'], 'enrolled': group['enrolled']})
    conflicts = []
    conflicts.extend(intervals)
    conflicts.extend(verified)
    if caps:
        conflicts.append({
            'kind': 'daily_cap',
            'days': caps,
            'message': '逐日退款不得超过报名；上述日期上限使约束无法同时满足',
        })
    return conflicts


def analyze(days, caps, intervals, verified):
    """求解退款对账。

    days: ISO 日期列表（窗口内全部自然日，顺序无关）
    caps: {day: enrolled}，必须覆盖 days
    intervals: [{date_from, date_to, total, label?}]
    verified: {day: refunds}
    """
    days = sorted(days)
    if not days:
        raise ValueError('对账窗口不能为空')
    for d in days:
        if d not in caps:
            raise ValueError('缺少日期 %s 的报名人次' % d)
        if int(caps[d]) < 0:
            raise ValueError('报名人次不能为负')
    for iv in intervals:
        if iv['date_from'] not in caps or iv['date_to'] not in caps:
            raise ValueError('区间必须落在对账窗口内')
        if iv['date_to'] < iv['date_from']:
            raise ValueError('区间开始日不得晚于结束日')
        if int(iv['total']) < 0:
            raise ValueError('区间总额不能为负')
    for d, value in verified.items():
        if d not in caps:
            raise ValueError('核实日期必须在窗口内')
        if int(value) < 0:
            raise ValueError('核实退款人次不能为负')

    groups, index = _groups_for(days, caps, intervals, verified)
    feasible, dist = _closure(len(days), groups)
    base = {
        'rule_version': RULE_VERSION,
        'inputs_checksum': inputs_checksum(days, caps, intervals, verified),
        'method': METHOD,
    }
    if not feasible:
        core = _minimal_conflict(len(days), groups)
        return {
            **base,
            'status': 'conflict',
            'solution': None,
            'ranges': [],
            'conflicts': _conflicts(core),
        }

    ranges = []
    for d in sorted(days):
        i = index[d]
        low = -dist[i][i - 1]
        high = dist[i - 1][i]
        # 日上限与非负约束已在图中，这里只做防御性收敛。
        low = max(0, low)
        high = min(int(caps[d]), high)
        if low > high:  # pragma: no cover - 与可行判定互斥
            raise ValueError('求解结果自相矛盾，请检查约束')
        ranges.append({
            'day': d,
            'min': int(low),
            'max': int(high),
            'fixed': bool(low == high),
            'enrolled': int(caps[d]),
        })

    if all(item['fixed'] for item in ranges):
        solution = {item['day']: item['min'] for item in ranges}
        return {
            **base,
            'status': 'unique',
            'solution': solution,
            'ranges': ranges,
            'conflicts': [],
        }
    return {
        **base,
        'status': 'multiple',
        'solution': None,
        'ranges': ranges,
        'conflicts': [],
    }


def validate_solution(days, caps, intervals, verified, solution):
    """返回解违反的约束列表；空列表表示满足全部约束。"""
    problems = []
    for d in days:
        value = solution.get(d)
        if not isinstance(value, int):
            problems.append({'kind': 'daily', 'day': d, 'message': '缺少整数解'})
            continue
        if value < 0:
            problems.append({'kind': 'daily', 'day': d, 'message': '退款为负'})
        if value > int(caps[d]):
            problems.append({'kind': 'daily', 'day': d, 'message': '退款超过报名'})
    for d, value in verified.items():
        if solution.get(d) != int(value):
            problems.append({'kind': 'verified', 'day': d, 'message': '核实日被改写'})
    for k, iv in enumerate(intervals):
        total = sum(int(solution.get(d, 0)) for d in day_range(iv['date_from'], iv['date_to']))
        if total != int(iv['total']):
            problems.append({
                'kind': 'interval',
                'index': k,
                'date_from': iv['date_from'],
                'date_to': iv['date_to'],
                'message': '区间合计 %s 不等于 %s' % (total, iv['total']),
            })
    return problems
