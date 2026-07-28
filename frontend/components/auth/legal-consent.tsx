import Link from "next/link";
import { useT } from "@/lib/i18n/provider";

export function LegalConsent({
  checked,
  onCheckedChange,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  const t = useT();

  return (
    <label className="flex cursor-pointer items-start gap-2.5 rounded-md border border-zinc-200/80 bg-white/45 p-3 text-xs leading-5 text-zinc-600 dark:border-white/10 dark:bg-white/[0.025] dark:text-zinc-300">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onCheckedChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-emerald-600"
      />
      <span>
        {t("auth.legal.agreePrefix")}
        <Link
          href="/terms"
          target="_blank"
          className="font-medium text-brand-600 underline underline-offset-2 dark:text-brand-400"
        >
          {t("legal.terms")}
        </Link>
        {t("auth.legal.and")}
        <Link
          href="/privacy"
          target="_blank"
          className="font-medium text-brand-600 underline underline-offset-2 dark:text-brand-400"
        >
          {t("legal.privacy")}
        </Link>
      </span>
    </label>
  );
}
