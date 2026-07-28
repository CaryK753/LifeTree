import Link from "next/link";
import { ArrowLeft, TreePine } from "lucide-react";

export interface LegalSection {
  title: string;
  paragraphs: string[];
  items?: string[];
}

export function LegalDocument({
  title,
  summary,
  version,
  sections,
}: {
  title: string;
  summary: string;
  version: string;
  sections: LegalSection[];
}) {
  return (
    <main className="min-h-dvh bg-zinc-50 px-4 py-6 text-zinc-900 safe-top safe-bottom dark:bg-[#0b0d12] dark:text-zinc-100 sm:px-6 sm:py-10">
      <article className="mx-auto w-full max-w-3xl">
        <header className="border-b border-zinc-200 pb-6 dark:border-zinc-800">
          <Link
            href="/auth"
            className="mb-6 inline-flex items-center gap-2 text-sm text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white"
          >
            <ArrowLeft className="h-4 w-4" />
            返回 LifeTree
          </Link>
          <div className="flex items-center gap-3">
            <TreePine className="h-7 w-7 text-emerald-600 dark:text-emerald-400" />
            <h1 className="text-2xl font-semibold sm:text-3xl">{title}</h1>
          </div>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            {summary}
          </p>
          <p className="mt-3 text-xs text-zinc-500">生效日期与版本：{version}</p>
        </header>

        <div className="space-y-8 py-8">
          {sections.map((section) => (
            <section key={section.title}>
              <h2 className="text-base font-semibold">{section.title}</h2>
              <div className="mt-3 space-y-3 text-sm leading-7 text-zinc-700 dark:text-zinc-300">
                {section.paragraphs.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
                {section.items && (
                  <ul className="list-disc space-y-2 pl-5">
                    {section.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          ))}
        </div>
      </article>
    </main>
  );
}
