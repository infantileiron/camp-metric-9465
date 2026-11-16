import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {table} from '../components/common/table.js';import {badge} from '../components/common/status.js';
const STATUS={pending_analysis:'待分析',pending_apply:'待应用',applied:'已应用'};const RESULT={unique:'唯一解',multiple:'多解',conflict:'无解'};
const fmtInterval=iv=>`${iv.date_from} ~ ${iv.date_to}＝${iv.total}${iv.label?'（'+iv.label+'）':''}`;
const input=(label,name,type,value,extra='')=>`<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
const text=(label,name,value,rows,extra='')=>`<label>${label}<textarea name="${name}" rows="${rows}" ${extra}>${esc(value)}</textarea></label>`;
function cases(){return (state.reconciliations||[]).map(r=>`<button class="study" data-recon-select="${r.id}">#${r.id} ${esc(r.class_code)} ${esc(r.date_from)}~${esc(r.date_to)} · ${esc(STATUS[r.state]||r.state)}${r.analysis?(' · '+esc(RESULT[r.analysis.status]||'')):''}${r.analysis?.stale?' · 依据已失效':''}</button>`).join('')}
function intervalsText(spec){return (spec?.intervals||[]).map(iv=>[iv.date_from,iv.date_to,iv.total,iv.label||''].join(',')).join('\n')}
function verifiedText(spec){return Object.entries(spec?.verified||{}).map(([d,v])=>d+','+v).join('\n')}
function detail(e){
 if(!e)return '<p class="notice">左侧选择一份对账，或用右侧表单新建。窗口最多31日，区间可以重叠；核实日必须落在窗口内。</p>';
 const spec=e.constraint_spec||{},a=e.analysis;
 let body=`<p>${esc(e.class_code)} · ${esc(e.date_from)} — ${esc(e.date_to)} · ${badge(STATUS[e.state]||e.state)}${a?(' · '+badge(RESULT[a.status]||a.status)):''}</p>`;
 body+=`<h3>财务区间（${(spec.intervals||[]).length} 条，允许重叠）</h3>${table(['起','止','合计','标签'],(spec.intervals||[]).map(iv=>[iv.date_from,iv.date_to,iv.total,iv.label||'—']))}`;
 const verified=Object.entries(spec.verified||{});
 body+=`<h3>已核实日期</h3>${verified.length?table(['日期','退款'],verified):'<p>未设置核实日。</p>'}`;
 if(!a)body+='<p class="notice">尚未分析。分析会冻结当前窗口内日报作为依据，之后日报变化不会改写这份依据。</p>';
 else if(a.stale)body+=`<p class="notice">上次分析已作废：${esc(a.stale_reason||'日报或约束已变化')}。请重新分析后再申请应用。</p>`;
 else if(a.status==='conflict')body+=`<p class="notice">无解：下列约束无法同时满足，请核对财务区间或核实日。</p>${table(['冲突项','说明'],(a.conflicts||[]).map(c=>[c.kind==='interval'?fmtInterval(c):c.kind==='verified'?('核实日 '+c.day+'＝'+c.refunds):(c.days||[]).map(d=>d.day).join('、'),c.message]))}`;
 else if(a.status==='multiple')body+=`<p class="notice">多解：无法唯一确定逐日退款，只展示各日可行范围，不能申请应用。请补充核实日或更细的财务区间。</p>${table(['日期','最小','最大','报名上限'],a.ranges.map(r=>[r.day,r.min,r.max,r.enrolled]))}`;
 else body+=`<p class="notice">唯一解：每个日期在全部可行整数解中取值相同。可申请应用；应用时若日报已被并发修改，将整单拒绝并要求重算。</p>${table(['日期','退款','报名上限'],a.ranges.map(r=>[r.day,r.min,r.enrolled]))}`;
 if(e.correction){const c=e.correction;body+=`<h3>已应用更正依据</h3><p>${esc(c.applied_at)} · ${esc(c.applied_by)} · 规则 ${esc(c.rule_version)} · 依据指纹 ${esc(c.basis_checksum).slice(0,12)}…</p>${table(['日期','原退款','更正后','是否变化'],c.days.map(d=>[d.day,d.before,d.after,d.changed?'是':'否']))}`;}
 const canAnalyze=e.state!=='applied'&&state.user?.role!=='viewer';
 const canApply=e.state==='pending_apply'&&state.user?.role==='admin';
 body+=`<p>${canAnalyze?`<button data-recon-analyze="${e.id}">${a?'重新分析':'分析'}</button>`:'<span class="tag">已应用，历史不可改写</span>'} ${canApply?`<button class="primary" data-recon-apply="${e.id}">申请应用（唯一解）</button>`:(e.state==='pending_apply'?'<span class="tag">待应用：仅负责人可应用</span>':'')} <button data-recon-export="${e.id}">下载对账 JSON</button></p>`;
 return body;
}
export function render(){
 const e=(state.reconciliations||[]).find(x=>x.id===state.reconSelected)||(state.reconciliations||[])[0]||null;
 const spec=e?.constraint_spec;
 const classes=[...new Set(state.facts.map(f=>f.class_code))];
 const chosen=spec?.class_code||classes[0]||'QH-01';
 const form=`<form id="recon">${e&&e.state!=='applied'?input('记录ID（修订时填写，已应用不可改）','record_id','number',e.id,'min=1'):input('记录ID（修订时填写，已应用不可改）','record_id','number','','min=1')}<label>班级<select name="class_code">${classes.map(c=>`<option value="${esc(c)}" ${c===chosen?'selected':''}>${esc(c)}</option>`).join('')}</select></label>${input('开始日','date_from','date',spec?.date_from||'2026-11-10','required')}${input('结束日','date_to','date',spec?.date_to||'2026-11-15','required')}${text('财务区间（每行：起,止,合计,标签）','intervals',intervalsText(spec)||'2026-11-10,2026-11-12,6,上半周\n2026-11-12,2026-11-15,7,下半周',4,'required')}${text('已核实日期（每行：日期,退款，可留空）','verified',verifiedText(spec),3)}<button class="primary">保存约束</button></form>`;
 return `<div class="split"><section class="panel"><h2>退款对账 / ${(state.reconciliations||[]).length} 份</h2>${cases()||'<p>尚无退款对账。</p>'}<hr>${detail(e)}</section><aside class="side"><h2>录入或修订约束</h2>${form}<p>录入后点“分析”。多解只给范围；唯一解才出现“申请应用”（仅负责人）。应用是单事务，重试不重复改写，试算看不到半单更正。</p></aside></div>`;
}
