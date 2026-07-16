export type InteractiveStandardizationStage = { markdown: string } | null;

export function afterLocalStandardization(markdown: string): InteractiveStandardizationStage {
  return { markdown };
}

export function shouldForceAi(stage: InteractiveStandardizationStage, markdown: string): boolean {
  return stage?.markdown === markdown;
}

export function isLocalStandardizationPayload(payload: any): boolean {
  return payload?.executionPath === "local" || payload?.cachedExecutionPath === "local";
}

export function nextStandardizationStageAfterResult({
  forceAi,
  markdown,
  payload,
}: {
  forceAi: boolean;
  markdown: string;
  payload: any;
}): InteractiveStandardizationStage {
  if (payload?.standardizer?.forceAiFailed) {
    return afterLocalStandardization(markdown);
  }
  if (forceAi) {
    return null;
  }
  return isLocalStandardizationPayload(payload) ? afterLocalStandardization(markdown) : null;
}
