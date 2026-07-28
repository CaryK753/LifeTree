"use client";

import { useMemo, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { AIAvatar } from "@/components/common/ai-avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import type { RuntimeCatalog, RuntimeModel, RuntimeProvider } from "@/lib/api";

interface Props {
  catalog?: RuntimeCatalog;
  value?: string;
  onValueChange: (modelId: string) => void;
}

interface ProviderGroup {
  provider: RuntimeProvider;
  models: RuntimeModel[];
}

export function ChatModelSelector({ catalog, value, onValueChange }: Props) {
  const [open, setOpen] = useState(false);
  const chatModels = useMemo(
    () => catalog?.models.filter((model) => model.capabilities.includes("chat")) ?? [],
    [catalog]
  );
  const selected = chatModels.find((model) => model.id === value)
    ?? chatModels.find((model) => model.id === catalog?.role_assignments.chat)
    ?? chatModels[0];
  const selectedProvider = catalog?.providers.find(
    (provider) => provider.id === selected?.provider_id
  );
  const groups = useMemo(() => {
    return (catalog?.providers ?? []).reduce<ProviderGroup[]>((result, provider) => {
      const models = chatModels.filter((model) => model.provider_id === provider.id);
      if (models.length) result.push({ provider, models });
      return result;
    }, []);
  }, [catalog?.providers, chatModels]);

  return (
    <ModelSelector open={open} onOpenChange={setOpen}>
      <ModelSelectorTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 max-w-48 gap-2 px-2.5">
          <AIAvatar
            protocol={selectedProvider?.protocol}
            name={`${selectedProvider?.name ?? ""} ${selected?.name ?? ""}`}
            size={16}
            className="shrink-0"
          />
          <span className="truncate text-xs">{selected?.display_name ?? "选择模型"}</span>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
        </Button>
      </ModelSelectorTrigger>
      <ModelSelectorContent className="max-w-lg" title="选择本次对话使用的模型">
        <ModelSelectorInput autoFocus placeholder="搜索模型或供应商" />
        <ModelSelectorList>
          <ModelSelectorEmpty>没有匹配的模型</ModelSelectorEmpty>
          {groups.map(({ provider, models }) => (
            <ModelSelectorGroup key={provider.id} heading={
              <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-zinc-500">
                <AIAvatar protocol={provider.protocol} name={provider.name} size={15} />
                <span>{provider.name}</span>
                {provider.managed_by === "admin" && (
                  <Badge variant="default" className="ml-auto text-[10px]">管理员提供</Badge>
                )}
              </div>
            }>
              {models.map((model) => (
                <ModelSelectorItem
                  key={model.id}
                  value={`${provider.name} ${model.display_name} ${model.name}`}
                  onSelect={() => {
                    onValueChange(model.id);
                    setOpen(false);
                  }}
                >
                  <AIAvatar protocol={provider.protocol} name={model.name} size={18} />
                  <ModelSelectorName>{model.display_name}</ModelSelectorName>
                  <span className="hidden truncate font-mono text-[10px] text-zinc-500 sm:block">
                    {model.name}
                  </span>
                  {model.id === selected?.id && <Check className="h-4 w-4 text-brand-500" />}
                </ModelSelectorItem>
              ))}
            </ModelSelectorGroup>
          ))}
        </ModelSelectorList>
      </ModelSelectorContent>
    </ModelSelector>
  );
}
