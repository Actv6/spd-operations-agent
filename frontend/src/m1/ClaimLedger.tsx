import { Button, Collapse, Tag } from "antd";
import type { AnalysisView, ReasonGroup } from "./types";

const labels = {
  tool_exact: "工具事实匹配",
  document_quote: "原文匹配",
  unverified: "待人工核实",
};

export function ClaimLedger({ analysis, onEvidence }: {
  analysis: AnalysisView;
  onEvidence: (id: string) => void;
}) {
  if (!analysis.claims?.length) return null;
  return <Collapse className="claim-ledger" items={[{
    key: "claims",
    label: `逐条依据 · ${analysis.claims.length} 条`,
    children: <ClaimEntries claims={analysis.claims} onEvidence={onEvidence} />,
  }]} />;
}

export function ClaimEntries({ claims, onEvidence }: {
  claims: NonNullable<AnalysisView["claims"]>;
  onEvidence: (id: string) => void;
}) {
  return <>
      <p className="secondary-text">工具事实与原文匹配分别核验；建议的适用性和待确认信息需人工复核。</p>
      <ol aria-label="逐条结论与依据">
        {claims.map((claim) => <li key={claim.id}>
          <Tag color={claim.verification === "unverified" ? "warning" : "default"}>
            {labels[claim.verification]}
          </Tag>
          <p>{claim.text}</p>
          {claim.evidence_ids.map((id, index) => <Button type="link" key={id}
            onClick={() => onEvidence(id)} aria-label={`查看${claim.id}的依据${index + 1}`}>
            查看依据 {index + 1}
          </Button>)}
        </li>)}
      </ol>
    </>;
}

export function ReasonBreakdown({ analysis }: { analysis: AnalysisView }) {
  return <ReasonGroups groups={analysis.reason_breakdown} />;
}

export function ReasonGroups({ groups }: { groups?: ReasonGroup[] | null }) {
  if (!groups?.length) return null;
  return <section className="reason-breakdown" aria-label="本次原因分项">
    <h4>原因分项</h4>
    <p className="secondary-text">按物资与科室组合计数；同一组合可能有多种原因，分项不能相加作为总数。</p>
    <ul>{groups.map((group) => <li key={group.reason}>
      <strong>{group.label} · {group.count} 个组合</strong>
      <p>{group.positions.map((p) => `${p.name} · ${p.department_name}`).join("；")}</p>
    </li>)}</ul>
  </section>;
}
