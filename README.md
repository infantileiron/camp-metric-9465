# 启航 · 训练营指标口径签核

把经营指标从口头约定变为可试算、可比较、可签核冻结的版本记录。

## 真实业务场景

启航训练营经营分析组服务四个线上/线下班级，每天收到班主任的 `启航_班级日报_20261115.xlsx`。原流程由分析员在工作簿计算实到率、结课达成率、退款占比，再把数字抄入经营会纪要。痛点是分子分母的过滤范围不一致、修改公式后旧结论失去依据、数据更正与口径变化无法分清。本项目接收上游班级日事实，替代口径登记/试算/差异解释，给下游经营负责人提供冻结依据。

三个业务实体：指标定义Metric（代码+版本唯一）、班级日事实Fact（班级+日期唯一）、试算签核快照Snapshot。四页是口径目录、事实校验、口径试算和签核历史；另有登录。后台worker真实计算，签核锁定口径与意见，后续事实修改不改变历史快照。第五页“退款对账”把财务的区间退款总额与日报逐日退款对齐。

|角色|权限|典型动作|
|---|---|---|
|admin|全部业务、审计、独占签核与对账应用|冻结经营依据、应用退款更正|
|analyst|口径/事实读写、试算、业务解释、退款对账分析、导出|建立净实到结课率v2并比较v1|
|viewer|业务只读及导出|下载签核快照，后端拒绝写入、任务提交与对账应用|

## 快速启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18210](http://localhost:18210)，后端 [localhost:19210/docs](http://localhost:19210/docs)，PostgreSQL端口17710。账号为 `admin@demo.local` / `analyst@demo.local` / `viewer@demo.local`，密码均 `Demo123!`。`SEED_DEMO=true`启动自动seed，手动重复不会新增同自然键或覆盖人工修订。种子为四班30日共120条事实（2026-10-17至11-15）、三类口径v1和三账号。

## 一天工作剧本

1. 08:50 viewer查看四班的报名/实到/结课/退款人次。
2. 09:00 analyst核对QH-01的2026-11-15事实，满足结课≤实到≤报名、退款≤报名。
3. 09:10 在事实校验录入新的班级日事实；修订时填写记录ID及完整字段。
4. 09:20 对completion v1（completed / attended）提交2026-10-17至11-15试算，刷新得到基线。
5. 09:30 在口径目录创建completion v2，分子completed，分母attended-refunds，写明“净实到”业务解释。
6. 09:40 新建v2试算，选择v1成功快照作为基线，核对比值差异、变更字段、日期窗和事实checksum。
7. 10:00 在签核历史填写不少于8字的解释，说明是否同时存在事实变化。
8. 10:10 admin签核；该版本不可覆盖。10:20 viewer下载 `camp-metric-<id>.json`。
9. 10:30 财务给出QH-01近一周区间退款：11-10~11-12共6、11-12~11-15共7。analyst在退款对账录入并分析；若多解，补一个核实日再分析。
10. 10:40 唯一解时admin申请应用，日报逐日退款写回；若期间有人改过日报，整单拒绝并要求重算。之后 viewer 下载 `refund-reconciliation-<id>.json`。

## 指标计算与安全白名单

允许字段为 enrolled/attended/completed/refunds，分别是班级日的报名/实到/结课/退款人次。表达式仅允许数字、字段、括号、+ − * /和一元正负；AST逐节点解释，禁止函数、属性访问、下标、幂运算、布尔、SQL和任意代码执行。表达式最多200字符/60个AST节点，常量绝对值≤1000000；非有限值、行级除零、极小分母造成超限结果显式失败。

按日期窗过滤事实，再按分子与分母各自的授课方式过滤；每行执行对应表达式，分子求和/分母求和，得到ratio。页面乘100展示百分比；不是日比率的简单平均。例如两班结课6/5、实到8/10，合计为11/18；v2扣除退款1/2后是11/15，绝对差11/90。分子分母过滤不同可能超过100%或为负，需人工解释，不自动截断。

外层总分母为0，value=null并显示undefined，不伪装0，可导出诊断但禁止签核。没有事实、非法行表达式使任务failed，修正后重新试算。每次冻结口径、事实、基线、日期窗及checksum。版本比较仅允许同指标代码，显示字段变化、绝对比值差和日期/事实是否一致；数据改变时不能把全部差异归因于口径。

签核需要已成功、非undefined、业务解释至少8字且口径仍与试算一致；试算后修订口径必须重算。签核后锁定口径版本和意见，事实更正不改旧快照。已有冻结版本可再次以新事实试算，但仍保留各次输入。

## 退款对账

财务按区间给出退款总人次（例如“11-10~11-12 共6人、11-12~11-15 共7人”），日报逐日退款却常对不上。退款对账接收一个班级在**最多31日**窗口内的财务区间（区间可重叠）和已核实日期，联合求解：

- 每个区间内逐日退款之和等于财务总额；
- 核实日退款等于核实值，不被改写；
- 每日退款为非负整数且不超过当日报名人次。

求解把区间写成前缀和之差，得到差分约束系统；系数矩阵为网络矩阵，整数右端项下实数可行即整数可行。Floyd-Warshall 闭包给出每个日期在**全部可行整数解**中的最小/最大值：负环即无解，上下界相等才算唯一解。因此多解只展示各日可行范围，绝不臆造一条“最像”的逐日明细。

|结果|页面展示|下一步|
|---|---|---|
|无解|移除过滤后仍不可满足的冲突区间/核实日/报名上限（最小冲突核心）|核对财务区间或核实日，修订后重新分析|
|多解|每日最小/最大可行退款，标注不能应用|补充核实日或更细区间后重新分析|
|唯一解|逐日退款与报名上限；“申请应用”仅负责人可见|admin 申请应用，写回日报退款|

**状态机**：`待分析 pending_analysis` →（唯一解）`待应用 pending_apply` →（admin 应用）`已应用 applied`。无解/多解分析后停留在待分析。已应用记录不可改约束、不可重新分析，历史签核与更正依据保持不变。

**分析依据固定**：分析时把窗口内班级日事实整体冻结进 `basis`，连同约束与事实指纹（`facts_checksum`、`inputs_checksum`）一并保存。之后即使日报被修订，已有分析仍指向原依据；修改约束会清空分析并要求重算。

**应用的并发与恢复**：应用前重新读取日报指纹，只要与冻结依据不同就**整单拒绝**、退回待分析并要求重算，不会“改一半”。应用在一个数据库事务内完成日报更正、对账状态与审计写入：进程中断整体回滚，日报不会出现半单更正，重试从头再来；已应用的重复请求按幂等处理，直接返回且不重复改写或记审计。事实与试算读取使用各自的已提交数据，试算过程中看不到未提交的半单更正。

**页面与导出**：退款对账页支持录入/修订约束（每行“起,止,合计,标签”；核实日每行“日期,退款”）、分析、查看歧义或冲突、申请应用，以及下载 `refund-reconciliation-<id>.json`。导出保留约束、解/可行范围/冲突、冻结事实与指纹、应用更正逐日前后值和时间戳。

## 工程、本地开发与范围

|层|技术|
|---|---|
|前端|原生ES modules/HTML/CSS，Nginx1.27|
|后端|Python3.11/FastAPI/SQLAlchemy/PyJWT|
|异步|Redis7队列，独立Python worker，心跳健康检查|
|数据库|PostgreSQL16，命名数据卷|

backend等待db/redis健康，worker再等backend，frontend等backend；恰好五服务。数据库、Redis及共享`/artifacts`结果卷持久化。Nginx `/api/`代理到后端根路由。清理用 `docker compose down -v --remove-orphans`。显式网络10.253.111.0/24规避当前机器默认地址池耗尽，可用NETWORK_SUBNET改。

环境变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。演示凭据/密钥部署时替换。本地开发先起db/redis，backend安装requirements，设置DATABASE_URL/REDIS_URL/JWT_SECRET后 `uvicorn src.main:app --reload`；前端保留同源Nginx或开发代理。

目录按backend/src的routes/controllers/services/models/schemas/middlewares/config/utils及frontend/src的api/stores/pages/components/hooks/utils/constants/types/router拆分。共享表格、字段、状态标签；表单hooks与HTML转义；请求ID/安全头中间件、业务审计和全局错误处理。枚举ROLES/STATES/MODES/APPROVALS/FIELDS/RECON_STATES/RECON_RESULTS位于后端constants/enums.py、schemas/business.py和前端constants/enums.js。ORM建初表，migrations/001_initial.sql与002_reconciliation.sql保留实际DDL；无在线版本迁移执行器。退款对账求解器在 `services/reconcile.py`（仅标准库，可直接单测），持久化与状态机在 `services/reconciliation.py`，测试在 `backend/tests/`：`python3 -m unittest discover tests`。

小型范围：逐条表单/API录入，无Excel批导、删除、分页或跨指标引用；单worker，启动恢复待处理任务。班级日事实是人次，不能解释为去重学员留存。签核只在站内，不外发邮件/电子签章。退款对账一次只处理一个班级、窗口最多31日，区间条数受请求上限约束；求解为精确整数可行域计算，不做成本优化或随机抽样。Google Fonts依赖网络，离线回退serif/sans-serif。测试证据在 `../../test-artifacts/gb-3111/TESTING.md`，源码无截图/日志。MIT License见LICENSE。
