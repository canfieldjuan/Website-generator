import { invoke } from "@tauri-apps/api/core";

import type {
  EngineArtifact,
  GenerationSettings,
  ProspectDocument,
} from "./state";

export type EngineStatus = {
  available: boolean;
  provider: string;
  model: string;
  base_url: string;
};

export type ImportedProspect = {
  file_name: string;
  document: ProspectDocument;
};

export type ConnectStatus = {
  entitlement_state: string;
  entitlement_active: boolean;
  provider_running: boolean;
  provider_managed: boolean;
};

export async function importProspect(): Promise<ImportedProspect | null> {
  return invoke<ImportedProspect | null>("import_prospect");
}

export async function exportProspect(
  prospect: ProspectDocument,
): Promise<string | null> {
  return invoke<string | null>("export_prospect", { prospect });
}

export async function checkEngine(
  generation: GenerationSettings,
): Promise<EngineStatus> {
  return invoke<EngineStatus>("engine_status", { generation });
}

export async function generateSite(
  prospect: ProspectDocument,
  generation: GenerationSettings,
): Promise<EngineArtifact> {
  return invoke<EngineArtifact>("generate_site", { prospect, generation });
}

export async function cancelGeneration(): Promise<boolean> {
  return invoke<boolean>("cancel_generation");
}

export async function saveArtifact(): Promise<string | null> {
  return invoke<string | null>("save_artifact");
}

export async function getConnectStatus(): Promise<ConnectStatus> {
  return invoke<ConnectStatus>("connect_status");
}

export async function installConnectEntitlement(): Promise<ConnectStatus | null> {
  return invoke<ConnectStatus | null>("install_connect_entitlement");
}

export async function startConnect(): Promise<ConnectStatus> {
  return invoke<ConnectStatus>("start_connect");
}

export async function stopConnect(): Promise<ConnectStatus> {
  return invoke<ConnectStatus>("stop_connect");
}
