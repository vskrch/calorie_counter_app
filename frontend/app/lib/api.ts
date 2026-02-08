export type UserSummary = {
  id: number;
  name: string;
  code_hint: string;
  created_at: string;
};

export type RegisterResponse = {
  user: UserSummary;
  code: string;
  message: string;
};

export type SessionResponse = {
  mode: "admin" | "user";
  user: UserSummary | null;
};

export type ImageAnalysisResult = {
  dish: string;
  meal_type: string;
  calories_kcal: number | null;
  protein_g: number | null;
  fiber_g: number | null;
  confidence_score: number | null;
  nutrients: string[];
  chemicals: string[];
  notes: string | null;
  source: string;
  model: string | null;
  raw: string | null;
};

export type MealEntry = {
  id: number;
  user_id: number;
  source: string;
  dish: string;
  meal_type: string;
  calories_kcal: number | null;
  protein_g: number | null;
  fiber_g: number | null;
  confidence_score: number | null;
  nutrients: string[];
  chemicals: string[];
  notes: string | null;
  eaten_at: string;
  created_at: string;
  updated_at: string;
};

export type SummaryResponse = {
  days: number;
  entries: number;
  calories_kcal: number;
  protein_g: number;
  fiber_g: number;
};

export type AdminOverview = {
  users: number;
  entries: number;
  calories_kcal: number;
};

export type AdminUser = {
  id: number;
  name: string;
  code_hint: string;
  created_at: string;
  entries: number;
  calories_kcal: number;
};

export type ResetCodeResponse = {
  user: UserSummary;
  new_code: string;
};

export type ProviderSessionStatus = {
  provider: string;
  connected: boolean;
  updated_at: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "";

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    let detail = "Request failed";
    try {
      const payload = await response.json();
      detail = payload?.detail ?? JSON.stringify(payload);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || "Request failed");
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function register(name: string) {
  return apiFetch<RegisterResponse>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function createSession(code: string) {
  return apiFetch<SessionResponse>("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}

export function getProfile(code: string) {
  return apiFetch<UserSummary>("/api/profile", {
    headers: { "X-Access-Code": code },
  });
}

export function getMeals(code: string, limit = 30) {
  return apiFetch<{ entries: MealEntry[]; total: number; limit: number; offset: number }>(
    `/api/meals?limit=${limit}`,
    {
      headers: { "X-Access-Code": code },
    },
  );
}

export function getSummary(code: string, days = 7) {
  return apiFetch<SummaryResponse>(`/api/summary?days=${days}`, {
    headers: { "X-Access-Code": code },
  });
}

export function deleteMeal(code: string, entryId: number) {
  return apiFetch<{ status: string }>(`/api/meals/${entryId}`, {
    method: "DELETE",
    headers: { "X-Access-Code": code },
  });
}

export async function analyzePhoto(
  code: string,
  file: File,
  provider: "perplexity" | "openrouter" | "perplexity_web",
  keys?: {
    perplexityApiKey?: string;
    openrouterApiKey?: string;
  },
  saveEntry = true,
) {
  const form = new FormData();
  form.append("image", file);
  form.append("provider", provider);
  form.append("save_entry", String(saveEntry));

  const headers: Record<string, string> = { "X-Access-Code": code };
  if (keys?.perplexityApiKey?.trim()) {
    headers["X-Perplexity-Api-Key"] = keys.perplexityApiKey.trim();
  }
  if (keys?.openrouterApiKey?.trim()) {
    headers["X-Openrouter-Api-Key"] = keys.openrouterApiKey.trim();
  }

  const response = await fetch(`${API_BASE}/api/analyze/photo`, {
    method: "POST",
    headers,
    body: form,
  });

  if (!response.ok) {
    let detail = "Image analysis failed";
    try {
      const payload = await response.json();
      detail = payload?.detail ?? detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  return (await response.json()) as ImageAnalysisResult;
}

export function analyzeManual(code: string, text: string, saveEntry = true) {
  return apiFetch<ImageAnalysisResult>("/api/analyze/manual", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Access-Code": code,
    },
    body: JSON.stringify({ text, save_entry: saveEntry }),
  });
}

export function adminOverview(adminCode: string) {
  return apiFetch<AdminOverview>("/api/admin/overview", {
    headers: { "X-Admin-Code": adminCode },
  });
}

export function adminUsers(adminCode: string) {
  return apiFetch<AdminUser[]>("/api/admin/users", {
    headers: { "X-Admin-Code": adminCode },
  });
}

export function adminResetCode(adminCode: string, userId: number) {
  return apiFetch<ResetCodeResponse>(`/api/admin/users/${userId}/reset-code`, {
    method: "POST",
    headers: { "X-Admin-Code": adminCode },
  });
}

export function adminDeleteUser(adminCode: string, userId: number) {
  return apiFetch<{ status: string }>(`/api/admin/users/${userId}`, {
    method: "DELETE",
    headers: { "X-Admin-Code": adminCode },
  });
}

export function adminPerplexityWebStatus(adminCode: string) {
  return apiFetch<ProviderSessionStatus>("/api/admin/providers/perplexity_web", {
    headers: { "X-Admin-Code": adminCode },
  });
}

export function adminConnectPerplexityWeb(adminCode: string, email: string, password: string) {
  return apiFetch<ProviderSessionStatus>("/api/admin/providers/perplexity_web", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Code": adminCode },
    body: JSON.stringify({ email, password }),
  });
}

export function adminDisconnectPerplexityWeb(adminCode: string) {
  return apiFetch<{ status: string }>("/api/admin/providers/perplexity_web", {
    method: "DELETE",
    headers: { "X-Admin-Code": adminCode },
  });
}
