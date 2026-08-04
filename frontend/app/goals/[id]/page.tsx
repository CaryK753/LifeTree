import { GoalDetailPage } from "@/components/goals/goal-detail-page";

export function generateStaticParams() {
  return [{ id: "_" }];
}

export default async function GoalDetailRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <GoalDetailPage goalId={id} />;
}
