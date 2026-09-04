export type ProspectDocument = Record<string, unknown>;

export type ProspectFields = {
  businessName: string;
  trade: "" | "plumber" | "hvac" | "electrician";
  city: string;
  state: string;
  phone: string;
  address: string;
  ownerEmail: string;
  formspreeEndpoint: string;
  servicesText: string;
};

export type GenerationSettings =
  | { provider: "local"; model: string; base_url: string }
  | { provider: "openrouter"; model: string; api_key: string };

export type EngineArtifact = {
  media_type: "text/html";
  display_name: string;
  byte_size: number;
  sha256: string;
  payload_base64: string;
};

const STRING_FIELD_MAP = {
  business_name: "businessName",
  city: "city",
  state: "state",
  phone: "phone",
  address: "address",
  owner_email: "ownerEmail",
  formspree_endpoint: "formspreeEndpoint",
} as const;

export function emptyProspectFields(): ProspectFields {
  return {
    businessName: "",
    trade: "",
    city: "",
    state: "IL",
    phone: "",
    address: "",
    ownerEmail: "",
    formspreeEndpoint: "",
    servicesText: "",
  };
}

export function fieldsFromProspect(document: ProspectDocument): ProspectFields {
  const fields = emptyProspectFields();
  for (const [documentKey, fieldKey] of Object.entries(STRING_FIELD_MAP)) {
    const value = document[documentKey];
    if (typeof value === "string") {
      fields[fieldKey] = value;
    } else if (value !== undefined && value !== null) {
      throw new Error(`${documentKey} must be text.`);
    }
  }
  const trade = document.trade;
  if (trade === "plumber" || trade === "hvac" || trade === "electrician") {
    fields.trade = trade;
  } else if (trade !== undefined && trade !== null) {
    throw new Error("trade must be plumber, hvac, or electrician.");
  }
  const services = document.services;
  if (Array.isArray(services)) {
    if (!services.every((value) => typeof value === "string")) {
      throw new Error("services must contain only text values.");
    }
    fields.servicesText = services.join("\n");
  } else if (services !== undefined && services !== null) {
    throw new Error("services must be a list of text values.");
  }
  return fields;
}

export function mergeProspectFields(
  source: ProspectDocument,
  fields: ProspectFields,
): ProspectDocument {
  const merged = structuredClone(source);
  for (const [documentKey, fieldKey] of Object.entries(STRING_FIELD_MAP)) {
    const value = fields[fieldKey].trim();
    if (value) {
      merged[documentKey] = value;
    } else {
      delete merged[documentKey];
    }
  }
  if (fields.trade) {
    merged.trade = fields.trade;
  } else {
    delete merged.trade;
  }
  const services = fields.servicesText
    .split(/\r?\n/)
    .map((service) => service.trim())
    .filter(Boolean);
  if (services.length) {
    merged.services = services;
  } else {
    delete merged.services;
  }
  return merged;
}

export function settingsForProvider(
  provider: "local" | "openrouter",
  values: {
    localModel: string;
    localBaseUrl: string;
    openRouterModel: string;
    openRouterApiKey: string;
  },
): GenerationSettings {
  if (provider === "local") {
    return {
      provider,
      model: values.localModel.trim(),
      base_url: values.localBaseUrl.trim(),
    };
  }
  return {
    provider,
    model: values.openRouterModel.trim(),
    api_key: values.openRouterApiKey,
  };
}

export function clearCloudCredentialOnProviderChange(
  previous: "local" | "openrouter",
  next: "local" | "openrouter",
  apiKey: string,
): string {
  return previous !== next ? "" : apiKey;
}

export function decodeArtifact(artifact: EngineArtifact): Uint8Array {
  if (
    artifact.media_type !== "text/html" ||
    !Number.isSafeInteger(artifact.byte_size) ||
    artifact.byte_size < 0 ||
    artifact.byte_size > 2 * 1024 * 1024 ||
    !/^[a-f0-9]{64}$/.test(artifact.sha256) ||
    typeof artifact.payload_base64 !== "string"
  ) {
    throw new Error("The generator returned an invalid website artifact.");
  }
  let binary: string;
  try {
    binary = atob(artifact.payload_base64);
  } catch {
    throw new Error("The generator returned unreadable website data.");
  }
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  if (bytes.byteLength !== artifact.byte_size) {
    throw new Error("The generated website size did not match its receipt.");
  }
  return bytes;
}

export class AttemptGate {
  private current = 0;

  begin(): number {
    this.current += 1;
    return this.current;
  }

  isCurrent(attempt: number): boolean {
    return attempt === this.current;
  }

  invalidate(): void {
    this.current += 1;
  }
}
