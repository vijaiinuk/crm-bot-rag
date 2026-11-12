// Friendly names for the generated API types (src/api/schema.d.ts, from `make admin-types`).
import type { components } from "./schema";

type S = components["schemas"];

export type Me = S["Me"];
export type Overview = S["Overview"];
export type DocumentSummary = S["DocumentSummary"];
export type DocumentDetail = S["DocumentDetail"];
export type DocumentVersion = S["DocumentVersion"];
export type DocumentVersionContent = S["DocumentVersionContent"];
export type Release = S["Release"];
export type ReleaseStatus = Release["status"];
export type DraftDiff = S["DraftDiff"];
export type ModuleChange = S["ModuleChange"];
export type GateCheck = S["GateCheck"];
export type Job = S["Job"];
export type JobAccepted = S["JobAccepted"];
export type PublishAccepted = S["PublishAccepted"];
export type RunAccepted = S["RunAccepted"];
export type EvalQuestion = S["EvalQuestion"];
export type EvalQuestionCreate = S["EvalQuestionCreate"];
export type Expected = S["Expected"];
export type EvalRun = S["EvalRun"];
export type EvalRunDetail = S["EvalRunDetail"];
export type EvalResult = S["EvalResult"];
export type CostSummary = S["CostSummary"];
export type ConversationSummary = S["ConversationSummary"];
export type ConversationDetail = S["ConversationDetail"];
export type ModelPrice = S["ModelPrice"];
export type AuditEntry = S["AuditEntry"];

export type AdminRole = "viewer" | "editor" | "publisher";
