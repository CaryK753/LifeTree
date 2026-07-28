export const TERMS_VERSION = "2026-07-28";
export const PRIVACY_VERSION = "2026-07-28";

export interface LegalConsentPayload {
  accepted_terms: true;
  terms_version: string;
  privacy_version: string;
}

export function currentLegalConsent(): LegalConsentPayload {
  return {
    accepted_terms: true,
    terms_version: TERMS_VERSION,
    privacy_version: PRIVACY_VERSION,
  };
}
