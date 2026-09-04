import { describe, expect, it } from "vitest";

import {
  AttemptGate,
  clearCloudCredentialOnProviderChange,
  decodeArtifact,
  fieldsFromProspect,
  mergeProspectFields,
  settingsForProvider,
  type EngineArtifact,
} from "./state";

describe("prospect projection", () => {
  it("does not invent a trade for a new or incomplete prospect", () => {
    const fields = fieldsFromProspect({});
    expect(fields.trade).toBe("");
    expect(fields.state).toBe("");
  });

  it("rejects unsupported known values instead of silently rewriting them", () => {
    expect(() => fieldsFromProspect({ trade: "roofer" })).toThrow("trade");
    expect(() => fieldsFromProspect({ phone: 2175550100 })).toThrow("phone");
    expect(() => fieldsFromProspect({ services: ["Repair", 42] })).toThrow(
      "services",
    );
  });

  it("preserves unknown imported fields while updating human fields", () => {
    const imported = {
      business_name: "Old Name",
      trade: "plumber",
      city: "Effingham",
      state: "IL",
      phone: "217-555-0100",
      reviews: [{ author: "A", text: "Careful work" }],
      custom_future_field: { retained: true },
    };
    const fields = fieldsFromProspect(imported);
    fields.businessName = "New Name";
    fields.servicesText = "Drain cleaning\n\n Water heaters ";

    const merged = mergeProspectFields(imported, fields);

    expect(merged.business_name).toBe("New Name");
    expect(merged.services).toEqual(["Drain cleaning", "Water heaters"]);
    expect(merged.reviews).toEqual(imported.reviews);
    expect(merged.custom_future_field).toEqual({ retained: true });
    expect(imported.business_name).toBe("Old Name");
    expect(imported).not.toHaveProperty("services");
  });

  it("removes known optional fields when the operator clears them", () => {
    const imported = {
      business_name: "Example Plumbing",
      trade: "plumber",
      city: "Effingham",
      state: "IL",
      phone: "217-555-0100",
      address: "100 Main St",
      owner_email: "owner@example.test",
      services: ["Drain cleaning"],
    };
    const fields = fieldsFromProspect(imported);
    fields.address = "";
    fields.ownerEmail = "";
    fields.servicesText = "";

    const merged = mergeProspectFields(imported, fields);

    expect(merged).not.toHaveProperty("address");
    expect(merged).not.toHaveProperty("owner_email");
    expect(merged).not.toHaveProperty("services");
  });
});

describe("provider session state", () => {
  it("clears a cloud key whenever the provider changes", () => {
    expect(
      clearCloudCredentialOnProviderChange("openrouter", "local", "secret"),
    ).toBe("");
    expect(
      clearCloudCredentialOnProviderChange("openrouter", "openrouter", "secret"),
    ).toBe("secret");
  });

  it("keeps local and cloud request shapes separate", () => {
    const values = {
      localModel: " qwen3-30b-a3b:latest ",
      localBaseUrl: " http://127.0.0.1:11434 ",
      openRouterModel: " anthropic/example ",
      openRouterApiKey: "secret",
    };

    expect(settingsForProvider("local", values)).toEqual({
      provider: "local",
      model: "qwen3-30b-a3b:latest",
      base_url: "http://127.0.0.1:11434",
    });
    expect(settingsForProvider("openrouter", values)).toEqual({
      provider: "openrouter",
      model: "anthropic/example",
      api_key: "secret",
    });
  });
});

describe("artifact boundary", () => {
  function artifact(payload: string, byteSize: number): EngineArtifact {
    return {
      media_type: "text/html",
      display_name: "preview.html",
      byte_size: byteSize,
      sha256: "a".repeat(64),
      payload_base64: payload,
    };
  }

  it("decodes an exact admitted artifact", () => {
    const html = "<body>Ready</body>";
    const payload = btoa(html);

    expect(new TextDecoder().decode(decodeArtifact(artifact(payload, html.length)))).toBe(
      html,
    );
  });

  it("rejects malformed base64, size drift, and oversized receipts", () => {
    expect(() => decodeArtifact(artifact("%%%", 3))).toThrow("unreadable");
    expect(() => decodeArtifact(artifact(btoa("abc"), 2))).toThrow("did not match");
    expect(() => decodeArtifact(artifact(btoa("a"), 2 * 1024 * 1024 + 1))).toThrow(
      "invalid",
    );
  });
});

describe("attempt gate", () => {
  it("rejects a result from an invalidated or superseded attempt", () => {
    const gate = new AttemptGate();
    const first = gate.begin();
    expect(gate.isCurrent(first)).toBe(true);
    gate.invalidate();
    expect(gate.isCurrent(first)).toBe(false);
    const second = gate.begin();
    const third = gate.begin();
    expect(gate.isCurrent(second)).toBe(false);
    expect(gate.isCurrent(third)).toBe(true);
  });
});
