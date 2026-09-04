import "./styles.css";

import {
  cancelGeneration,
  checkEngine,
  exportProspect,
  generateSite,
  importProspect,
  saveArtifact,
} from "./engine";
import {
  AttemptGate,
  clearCloudCredentialOnProviderChange,
  decodeArtifact,
  documentForGeneration,
  emptyProspectFields,
  fieldsFromProspect,
  installPreviewImageFallbacks,
  mergeProspectFields,
  settingsForProvider,
  type ProspectDocument,
  type ProspectFieldKey,
  type ProspectFields,
} from "./state";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("Website Generator could not start.");

app.innerHTML = `
  <div class="app-shell" data-mobile-view="facts">
    <header class="topbar">
      <div class="brand-lockup">
        <div class="registration-mark" aria-hidden="true"><span></span><span></span></div>
        <div>
          <p class="eyebrow">Local website workshop</p>
          <h1>Website Generator</h1>
        </div>
      </div>
      <div class="topbar-actions">
        <button class="button button--quiet" id="import-button" type="button">Import JSON</button>
        <button class="button button--quiet" id="export-button" type="button">Export JSON</button>
      </div>
    </header>

    <nav class="mobile-switcher" aria-label="Workspace view">
      <button type="button" data-view-button="facts" aria-pressed="true">Build brief</button>
      <button type="button" data-view-button="preview" aria-pressed="false">Preview</button>
    </nav>

    <main class="workspace">
      <aside class="build-line" aria-label="Build progress">
        <ol>
          <li data-stage="facts" data-state="active"><span>1</span><b>Facts</b></li>
          <li data-stage="generate"><span>2</span><b>Generate</b></li>
          <li data-stage="review"><span>3</span><b>Review</b></li>
          <li data-stage="save"><span>4</span><b>Save</b></li>
        </ol>
      </aside>

      <section class="brief-panel" aria-labelledby="brief-title">
        <div class="panel-heading">
          <div>
            <p class="section-kicker">Verified inputs</p>
            <h2 id="brief-title">Build brief</h2>
          </div>
          <p class="source-note" id="source-note">New prospect</p>
        </div>

        <form id="prospect-form" novalidate>
          <fieldset>
            <legend>Business</legend>
            <div class="field-grid field-grid--two">
              <label class="field field--wide">
                <span>Business name <em>Required</em></span>
                <input id="business-name" autocomplete="organization" required />
              </label>
              <label class="field">
                <span>Trade <em>Required</em></span>
                <select id="trade" required>
                  <option value="">Choose a trade</option>
                  <option value="plumber">Plumbing</option>
                  <option value="hvac">HVAC</option>
                  <option value="electrician">Electrical</option>
                </select>
              </label>
              <label class="field">
                <span>Phone <em>Required</em></span>
                <input id="phone" autocomplete="tel" inputmode="tel" required />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Service area</legend>
            <div class="field-grid field-grid--location">
              <label class="field">
                <span>City <em>Required</em></span>
                <input id="city" autocomplete="address-level2" required />
              </label>
              <label class="field field--state">
                <span>State <em>Required</em></span>
                <input id="state" autocomplete="address-level1" minlength="2" maxlength="2" pattern="[A-Za-z]{2}" title="Enter a two-letter state abbreviation" required />
              </label>
              <label class="field field--wide">
                <span>Street address <small>Optional</small></span>
                <input id="address" autocomplete="street-address" />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Services and contact</legend>
            <label class="field">
              <span>Services <small>One per line</small></span>
              <textarea id="services" rows="5" placeholder="Drain cleaning&#10;Water heater repair&#10;Fixture installation"></textarea>
            </label>
            <div class="field-grid field-grid--two">
              <label class="field">
                <span>Business email <small>Optional</small></span>
                <input id="owner-email" autocomplete="email" type="email" />
              </label>
              <label class="field">
                <span>Formspree endpoint <small>Optional</small></span>
                <input id="formspree-endpoint" type="url" placeholder="https://formspree.io/f/..." />
              </label>
            </div>
          </fieldset>

          <fieldset class="provider-fieldset">
            <legend>Generation</legend>
            <div class="provider-options" role="radiogroup" aria-label="Generation provider">
              <label class="provider-card">
                <input type="radio" name="provider" value="local" checked />
                <span><b>Local Ollama</b><small>Private · runs on this computer</small></span>
              </label>
              <label class="provider-card">
                <input type="radio" name="provider" value="openrouter" />
                <span><b>OpenRouter</b><small>Explicit cloud session</small></span>
              </label>
            </div>

            <div class="provider-settings" id="local-settings">
              <label class="field">
                <span>Local model</span>
                <input id="local-model" value="qwen3-30b-a3b:latest" class="machine-input" spellcheck="false" required />
              </label>
              <label class="field">
                <span>Ollama address</span>
                <input id="local-base-url" value="http://127.0.0.1:11434" type="url" class="machine-input" spellcheck="false" required />
              </label>
            </div>

            <div class="provider-settings" id="openrouter-settings" hidden>
              <label class="field">
                <span>OpenRouter model</span>
                <input id="openrouter-model" placeholder="anthropic/claude-sonnet-4.5" class="machine-input" spellcheck="false" required disabled />
              </label>
              <label class="field">
                <span>API key <small>Held for this session only</small></span>
                <input id="openrouter-key" type="password" autocomplete="off" class="machine-input" spellcheck="false" required disabled />
              </label>
            </div>

            <button class="text-action" id="check-model-button" type="button">Check model connection</button>
          </fieldset>
        </form>

        <div class="brief-actions">
          <button class="button button--primary" id="generate-button" type="button">
            <span>Generate website</span><span aria-hidden="true">→</span>
          </button>
          <button class="button button--danger" id="cancel-button" type="button" hidden>Cancel generation</button>
        </div>
      </section>

      <section class="preview-panel" aria-labelledby="preview-title">
        <div class="preview-toolbar">
          <div>
            <p class="section-kicker">Admitted output</p>
            <h2 id="preview-title">Customer preview</h2>
          </div>
          <button class="button button--save" id="save-button" type="button" disabled>Save HTML</button>
        </div>
        <div class="status-strip" id="status-strip" data-tone="neutral" aria-live="polite">
          <span class="status-dot" aria-hidden="true"></span>
          <p id="status-message">Add the prospect facts, then generate a website.</p>
        </div>
        <div class="preview-frame-wrap" id="preview-wrap" data-empty="true">
          <div class="empty-preview" id="empty-preview">
            <div class="page-outline" aria-hidden="true"><i></i><i></i><i></i></div>
            <h3>Your generated page will appear here</h3>
            <p>The preview is sandboxed and cannot run scripts or submit forms.</p>
          </div>
          <iframe id="site-preview" title="Generated customer website" sandbox="allow-same-origin" referrerpolicy="no-referrer" hidden></iframe>
          <div class="generation-sweep" aria-hidden="true"></div>
        </div>
        <div class="artifact-receipt" id="artifact-receipt" hidden>
          <span id="artifact-name"></span>
          <span id="artifact-size"></span>
        </div>
      </section>
    </main>
  </div>
`;

function element<T extends HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing application control: ${id}`);
  return value as T;
}

const shell = document.querySelector<HTMLElement>(".app-shell")!;
const form = element<HTMLFormElement>("prospect-form");
const importButton = element<HTMLButtonElement>("import-button");
const exportButton = element<HTMLButtonElement>("export-button");
const checkModelButton = element<HTMLButtonElement>("check-model-button");
const statusStrip = element<HTMLElement>("status-strip");
const statusMessage = element<HTMLElement>("status-message");
const generateButton = element<HTMLButtonElement>("generate-button");
const cancelButton = element<HTMLButtonElement>("cancel-button");
const saveButton = element<HTMLButtonElement>("save-button");
const preview = element<HTMLIFrameElement>("site-preview");
const previewWrap = element<HTMLElement>("preview-wrap");
const emptyPreview = element<HTMLElement>("empty-preview");
const receipt = element<HTMLElement>("artifact-receipt");
const openRouterKey = element<HTMLInputElement>("openrouter-key");

let sourceDocument: ProspectDocument = {};
let activeProvider: "local" | "openrouter" = "local";
let previewUrl: string | null = null;
let busy = false;
let activeGeneration: Promise<void> | null = null;
const attempts = new AttemptGate();
const editedProspectFields = new Set<ProspectFieldKey>();

preview.addEventListener("load", () => {
  const previewDocument = preview.contentDocument;
  if (!previewDocument) return;
  installPreviewImageFallbacks(Array.from(previewDocument.images));
});

const prospectControlFields: Record<string, ProspectFieldKey> = {
  "business-name": "businessName",
  trade: "trade",
  city: "city",
  state: "state",
  phone: "phone",
  address: "address",
  "owner-email": "ownerEmail",
  "formspree-endpoint": "formspreeEndpoint",
  services: "servicesText",
};

function inputValue(id: string): string {
  return element<HTMLInputElement | HTMLTextAreaElement>(id).value;
}

function selectedProvider(): "local" | "openrouter" {
  const checked = form.querySelector<HTMLInputElement>('input[name="provider"]:checked');
  return checked?.value === "openrouter" ? "openrouter" : "local";
}

function syncProviderFields(provider: "local" | "openrouter"): void {
  const localSettings = element<HTMLElement>("local-settings");
  const openRouterSettings = element<HTMLElement>("openrouter-settings");
  localSettings.hidden = provider !== "local";
  openRouterSettings.hidden = provider !== "openrouter";
  localSettings.querySelectorAll<HTMLInputElement>("input").forEach((input) => {
    input.disabled = provider !== "local";
  });
  openRouterSettings.querySelectorAll<HTMLInputElement>("input").forEach((input) => {
    input.disabled = provider !== "openrouter";
  });
  checkModelButton.textContent = provider === "local" ? "Check model connection" : "Validate cloud settings";
}

function collectFields(): ProspectFields {
  return {
    businessName: inputValue("business-name"),
    trade: element<HTMLSelectElement>("trade").value as ProspectFields["trade"],
    city: inputValue("city"),
    state: inputValue("state"),
    phone: inputValue("phone"),
    address: inputValue("address"),
    ownerEmail: inputValue("owner-email"),
    formspreeEndpoint: inputValue("formspree-endpoint"),
    servicesText: inputValue("services"),
  };
}

function writeFields(fields: ProspectFields): void {
  element<HTMLInputElement>("business-name").value = fields.businessName;
  element<HTMLSelectElement>("trade").value = fields.trade;
  element<HTMLInputElement>("city").value = fields.city;
  element<HTMLInputElement>("state").value = fields.state;
  element<HTMLInputElement>("phone").value = fields.phone;
  element<HTMLInputElement>("address").value = fields.address;
  element<HTMLInputElement>("owner-email").value = fields.ownerEmail;
  element<HTMLInputElement>("formspree-endpoint").value = fields.formspreeEndpoint;
  element<HTMLTextAreaElement>("services").value = fields.servicesText;
}

function currentDocument(): ProspectDocument {
  return mergeProspectFields(sourceDocument, collectFields(), editedProspectFields);
}

function recordProspectEdit(target: EventTarget | null): void {
  if (!(target instanceof HTMLElement)) return;
  const field = prospectControlFields[target.id];
  if (field) editedProspectFields.add(field);
}

function currentGeneration() {
  return settingsForProvider(selectedProvider(), {
    localModel: inputValue("local-model"),
    localBaseUrl: inputValue("local-base-url"),
    openRouterModel: inputValue("openrouter-model"),
    openRouterApiKey: openRouterKey.value,
  });
}

function setStatus(message: string, tone: "neutral" | "working" | "success" | "error" = "neutral"): void {
  statusMessage.textContent = message;
  statusStrip.dataset.tone = tone;
}

function setStage(stage: "facts" | "generate" | "review" | "save"): void {
  const order = ["facts", "generate", "review", "save"];
  const current = order.indexOf(stage);
  document.querySelectorAll<HTMLElement>("[data-stage]").forEach((item) => {
    const index = order.indexOf(item.dataset.stage ?? "");
    item.dataset.state = index < current ? "complete" : index === current ? "active" : "";
  });
}

function clearPreview(): void {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  preview.removeAttribute("src");
  preview.hidden = true;
  emptyPreview.hidden = false;
  previewWrap.dataset.empty = "true";
  receipt.hidden = true;
  saveButton.disabled = true;
}

function setBusy(value: boolean, cancellable = true): void {
  busy = value;
  form.toggleAttribute("inert", value);
  importButton.disabled = value;
  exportButton.disabled = value;
  checkModelButton.disabled = value;
  generateButton.disabled = value;
  cancelButton.hidden = !value || !cancellable;
  previewWrap.dataset.generating = String(value && cancellable);
}

function showError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  setStatus(message || "Website generation failed.", "error");
}

form.addEventListener("input", (event) => {
  recordProspectEdit(event.target);
  if (event.target instanceof HTMLInputElement && event.target.name === "provider") return;
  if (!busy && !saveButton.disabled) {
    attempts.invalidate();
    clearPreview();
    setStage("facts");
    setStatus("The brief changed. Generate again to review the new version.");
  }
});

form.addEventListener("change", (event) => {
  recordProspectEdit(event.target);
  if (!(event.target instanceof HTMLInputElement) || event.target.name !== "provider") return;
  const next = selectedProvider();
  openRouterKey.value = clearCloudCredentialOnProviderChange(activeProvider, next, openRouterKey.value);
  activeProvider = next;
  syncProviderFields(next);
  clearPreview();
  setStage("facts");
  setStatus(next === "local" ? "Local Ollama selected." : "OpenRouter selected for this session only.");
});

importButton.addEventListener("click", async () => {
  try {
    const imported = await importProspect();
    if (!imported) return;
    const fields = fieldsFromProspect(imported.document);
    sourceDocument = imported.document;
    editedProspectFields.clear();
    writeFields(fields);
    clearPreview();
    setStage("facts");
    element<HTMLElement>("source-note").textContent = imported.file_name;
    setStatus("Prospect JSON imported. Review the facts before generating.", "success");
  } catch (error) {
    showError(error);
  }
});

exportButton.addEventListener("click", async () => {
  try {
    const saved = await exportProspect(currentDocument());
    if (saved) setStatus(`Prospect JSON saved to ${saved}.`, "success");
  } catch (error) {
    showError(error);
  }
});

checkModelButton.addEventListener("click", async () => {
  setBusy(true, false);
  setStatus("Checking the selected model…", "working");
  try {
    const status = await checkEngine(currentGeneration());
    if (selectedProvider() === "openrouter") {
      setStatus(
        status.available
          ? "OpenRouter settings are accepted. The connection will be verified when you generate."
          : "Complete the OpenRouter model and API key settings.",
        status.available ? "success" : "error",
      );
      return;
    }
    setStatus(
      status.available
        ? `${status.model} is ready.`
        : `${status.model} is not available. Start Ollama and load that model.`,
      status.available ? "success" : "error",
    );
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

generateButton.addEventListener("click", async () => {
  if (!form.reportValidity()) {
    setStatus("Complete every required business field before generating.", "error");
    return;
  }
  clearPreview();
  const attempt = attempts.begin();
  setBusy(true);
  setStage("generate");
  setStatus("Generating and checking the website…", "working");
  const operation = (async () => {
    try {
      sourceDocument = currentDocument();
      editedProspectFields.clear();
      const artifact = await generateSite(
        documentForGeneration(sourceDocument),
        currentGeneration(),
      );
      if (!attempts.isCurrent(attempt)) return;
      const bytes = decodeArtifact(artifact);
      const htmlBuffer = new ArrayBuffer(bytes.byteLength);
      new Uint8Array(htmlBuffer).set(bytes);
      previewUrl = URL.createObjectURL(new Blob([htmlBuffer], { type: "text/html" }));
      preview.src = previewUrl;
      preview.hidden = false;
      emptyPreview.hidden = true;
      previewWrap.dataset.empty = "false";
      element<HTMLElement>("artifact-name").textContent = artifact.display_name;
      element<HTMLElement>("artifact-size").textContent = `${Math.ceil(bytes.byteLength / 1024)} KB`;
      receipt.hidden = false;
      saveButton.disabled = false;
      setStage("review");
      setStatus("Website generated and admitted. Review it before saving.", "success");
      if (window.matchMedia("(max-width: 926px)").matches) setMobileView("preview");
    } catch (error) {
      if (attempts.isCurrent(attempt)) showError(error);
    } finally {
      if (attempts.isCurrent(attempt)) setBusy(false);
    }
  })();
  activeGeneration = operation;
  await operation;
  if (activeGeneration === operation) activeGeneration = null;
});

cancelButton.addEventListener("click", async () => {
  attempts.invalidate();
  setBusy(true, false);
  setStatus("Cancelling generation…", "working");
  const operation = activeGeneration;
  try {
    const cancelled = await cancelGeneration();
    if (operation) await operation;
    setStatus(cancelled ? "Generation cancelled." : "No generation was running.");
  } catch (error) {
    if (operation) await operation;
    showError(error);
  } finally {
    setBusy(false);
    setStage("facts");
  }
});

saveButton.addEventListener("click", async () => {
  try {
    const saved = await saveArtifact();
    if (!saved) return;
    setStage("save");
    setStatus(`Website saved to ${saved}.`, "success");
  } catch (error) {
    showError(error);
  }
});

function setMobileView(view: "facts" | "preview"): void {
  shell.dataset.mobileView = view;
  document.querySelectorAll<HTMLButtonElement>("[data-view-button]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.viewButton === view));
  });
}

document.querySelectorAll<HTMLButtonElement>("[data-view-button]").forEach((button) => {
  button.addEventListener("click", () => setMobileView(button.dataset.viewButton === "preview" ? "preview" : "facts"));
});

window.addEventListener("beforeunload", () => {
  openRouterKey.value = "";
  if (previewUrl) URL.revokeObjectURL(previewUrl);
});

writeFields(emptyProspectFields());
