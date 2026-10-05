export type Stage = 'pending' | 'review' | 'active' | 'done';
export type Page = 'overview' | 'exceptions' | 'tasks' | 'data' | 'knowledge';
export type Risk = 'shortage' | 'expiry' | 'quality' | 'order';
export interface Inventory { id: string; hospital_id: string; department_id: string; product_id: string; name: string; department: string; category: string; base_unit: string; available_base: number; on_hand_base: number; frozen_base: number; daily_avg: number | null; observed_days: number; coverage_days: number | null; supplier_lead_days: number | null; snapshot_at: string; units_per_purchase_pack: number; }
export interface Batch { id: string; product_id: string; hospital_id: string; expiry_date: string; on_hand_base: number; frozen_base: number; status: string; }
export interface Order { id: string; product_id: string; hospital_id: string; ordered_base: number; received_base: number; cancelled_base: number; outstanding_base: number; expected_arrival_date: string; }
export interface Knowledge { id: string; title: string; version: string; status: string; effective_from: string; effective_until: string | null; allowed_hospitals: string[]; content: string; }
export interface Demo { inventory: Inventory[]; batches: Batch[]; orders: Order[]; documents: Knowledge[]; manifest: { as_of: string; counts: Record<string, number> }; }
export interface Task { id: string; product: string; hospital: string; title: string; type: Risk; stage: Stage; owner: string; due: string; note: string; history: string[]; }
export const STAGES: Record<Stage, string> = {pending:'待核查',review:'待确认',active:'处理中',done:'已完成'};
export const RISKS: Record<Risk, string> = {shortage:'缺货风险',expiry:'效期核查',quality:'数据核查',order:'到货确认'};
export const OWNERS = ['驻点专员 A','商务专员 A','质量专员 A'];
export const SEED_TASKS: Task[] = [
  ['T001','SIM-P001','核查生化清洗液库存','shortage','pending','','14:00'],
  ['T002','SIM-P006','补全反应杯消耗记录','quality','pending','','16:00'],
  ['T003','SIM-P007','刷新采样管库存快照','quality','pending','','17:00'],
  ['T004','SIM-P008','确认样本保存管交期','order','review','商务专员 A','15:00'],
  ['T005','SIM-P009','复核滤芯吸头未到货量','order','review','商务专员 A','16:30'],
  ['T006','SIM-P003','核查试纸临期批次','expiry','active','质量专员 A','18:00'],
  ['T007','SIM-P004','复核过期批次隔离状态','expiry','active','质量专员 A','17:00'],
  ['T008','SIM-P005','确认低频物资实际需求','quality','active','驻点专员 A','17:30'],
].map(([id,product,title,type,stage,owner,time])=>({id,product,hospital:'SIM-HA',title,type:type as Risk,stage:stage as Stage,owner,due:`2026-09-27T${time}`,note:'',history:[]}));
export const STORAGE_KEY = 'spd-ui-prototype-v1';
export function initialTasks(): Task[] { try { const raw=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null'); if(Array.isArray(raw)&&raw.length===SEED_TASKS.length&&SEED_TASKS.every(seed=>raw.some(t=>t.id===seed.id&&t.product===seed.product&&t.hospital===seed.hospital&&t.stage in STAGES&&typeof t.title==='string'&&typeof t.owner==='string'&&typeof t.due==='string'&&typeof t.note==='string'&&Array.isArray(t.history)))) return raw; } catch { /* Recover demo defaults on unavailable/invalid storage. */ } return structuredClone(SEED_TASKS); }
export function number(n:number|null|undefined) { return n == null ? '待核实' : Number.isInteger(n) ? n.toLocaleString('zh-CN') : n.toFixed(1); }
export function summary(t:Task, row:Inventory) {
  if(t.id==='T001') return `${number(row.available_base)} ${row.base_unit} · 预计可用 ${number(row.coverage_days)} 天`;
  if(t.id==='T002') return `近14天仅有 ${row.observed_days} 天记录`;
  if(t.id==='T003') return '库存快照距基准时间 72 小时';
  if(t.id==='T004') return '供应商交期缺失 · 待补充';
  if(t.id==='T005') return '订购 100 盒 · 尚有 50 盒未到';
  if(t.id==='T006') return '临期批次 300 筒 · 剩余 10 天';
  if(t.id==='T007') return `过期冻结 ${row.frozen_base} 盒 · 不计可用`;
  return '近14天零消耗 · 需求待核实';
}
export function procedure(t:Task): string[][] {
  if(t.type==='shortage') return [['核对账实库存','核对库存数量与冻结状态，确认差异。'],['确认供应商交期','核实预计到货时间及未同步订单。'],['记录补货安排','确认处理人，记录拟采取的业务措施。']];
  if(t.type==='expiry') return [['核对批次与效期','核查剩余效期和当前库存状态。'],['确认处置要求','向质量人员核实项目和产品要求。'],['记录处理结果','记录处理措施，不自动调拨或报废。']];
  if(t.type==='order') return [['核对订单明细','确认已到货、取消和未到货数量。'],['联系业务负责人','补全交期或确认预计到货时间。'],['记录核查结果','更新处理记录，保留核查依据。']];
  return [['核对原始记录','核查数据时间、完整性和实际需求。'],['补充缺失信息','由驻点人员确认，缺失不视为零。'],['记录核查结果','记录补充情况，再重新评估风险。']];
}
