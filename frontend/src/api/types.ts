// TypeScript mirrors of the verified backend contracts. Fields the backend
// persists as null must remain `| null` here so the UI never implies a value
// the backend does not know.

export type RunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/** Authenticated user returned by the backend. `password_hash` is never exposed. */
export interface User {
  user_id: string;
  email: string;
  display_name: string | null;
  created_at: string;
}

/** Request body for creating an account (POST /api/auth/register). */
export interface UserRegister {
  email: string;
  password: string;
  display_name?: string | null;
}

/** Request body for signing in (POST /api/auth/login). */
export interface UserLogin {
  email: string;
  password: string;
}

/**
 * Response body for register/login: the one-time bearer token plus the user.
 * The token must be echoed as `Authorization: Bearer <token>` on all later
 * requests; it never appears again after this response.
 */
export interface AuthResponse {
  token: string;
  user: User;
}

export type RunPhase =
  | "discovery"
  | "research"
  | "qualification"
  | "contact_and_lead"
  | "completed";

export interface DiscoveryRun {
  run_id: string;
  status: RunStatus;
  target_lead_count: number;
  qualified_lead_count: number;
  started_at: string;
  completed_at: string | null;
  current_phase: RunPhase | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

export type VerificationStatus = "unverified" | "evidenced" | "verified";

export type ContactReadiness =
  | "evidenced_contact"
  | "named_contact_no_email"
  | "public_email_available"
  | "company_contact_available"
  | "no_contact_found";

export interface Contact {
  contact_id: string;
  candidate_id: string;
  full_name: string;
  role: string | null;
  email: string | null;
  evidence_ids: string[];
  verification_status: VerificationStatus;
  created_at: string;
}

export interface QualifiedLead {
  lead_id: string;
  run_id: string;
  candidate_id: string;
  company_name: string;
  description: string | null;
  industry_or_sector: string | null;
  ceo_or_cofounder_name: string | null;
  verified_email: string | null;
  contact_readiness: ContactReadiness | null;
  evidence_ids: string[];
  qualification_id: string | null;
  created_at: string;
}

export interface RunResults {
  run: DiscoveryRun;
  funnel: RunFunnel;
  contact_breakdown: ContactReadinessBreakdown;
  candidate_summary: CandidateSummary;
  candidates: CandidateAnalysis[];
  leads: QualifiedLead[];
  contacts: Contact[];
}

export interface CandidateSummary {
  company_qualified: number;
  near_qualified: number;
  not_qualified: number;
  not_evaluated: number;
  analyzed_total: number;
}

/** Persisted criterion outcome. "none" means no criterion row was ever written. */
export type CriterionStatus =
  | "pass"
  | "fail"
  | "insufficient_evidence"
  | "none"
  | "not_evaluated";

export type Classification =
  | "company_qualified"
  | "near_qualified"
  | "not_qualified"
  | "not_evaluated";

export interface CriterionResultSummary {
  status: CriterionStatus;
  reasons: string[];
}

export interface BlockingCriterion {
  criterion: "financial" | "tech_platform" | "us_presence";
  status: "fail" | "insufficient_evidence";
  reasons: string[];
}

export interface CandidateAnalysis {
  candidate_id: string;
  company_name: string;
  description: string | null;
  industry_or_sector: string | null;
  classification: Classification;
  overall_status: string | null;
  passed_criteria_count: number;
  criteria: {
    financial: CriterionResultSummary;
    tech_platform: CriterionResultSummary;
    us_presence: CriterionResultSummary;
  };
  blocking_criteria: BlockingCriterion[];
}

export interface RunFunnel {
  sources_discovered: number;
  sources_researched: number;
  candidates_extracted: number;
  candidates_evaluated: number;
  financial_pass: number;
  tech_pass: number;
  geography_pass: number;
  company_qualified: number;
}

export interface ContactReadinessBreakdown {
  evidenced_contact: number;
  named_contact_no_email: number;
  public_email_available: number;
  company_contact_available: number;
  no_contact_found: number;
  not_enriched: number;
}

export interface ActivityEvent {
  event_id: string;
  run_id: string;
  timestamp: string;
  phase: RunPhase;
  event_type: string;
  message: string;
  related_candidate_id: string | null;
  related_source_id: string | null;
}

/** FastAPI validation error element (422). */
export interface ValidationErrorItem {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}