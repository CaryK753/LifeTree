import { DecisionTreePage } from "@/components/tree/decision-tree-page";

export function generateStaticParams() {
  return [{ goalId: "_" }];
}

export default async function DecisionTreeRoute({
  params,
}: {
  params: Promise<{ goalId: string }>;
}) {
  const { goalId } = await params;
  return <DecisionTreePage goalId={goalId} />;
}
