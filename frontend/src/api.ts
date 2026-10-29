import { readAccessToken } from "./auth";

export type DonationStatus = "available" | "claimed" | "picked_up" | "cancelled" | "expired";

export interface Donation {
  id: string;
  donor_id: string;
  food_name: string;
  description: string;
  category: string;
  quantity: number;
  unit: string;
  available_at: string | null;
  pickup_deadline: string;
  pickup_location: string;
  status: DonationStatus;
  claimed_by: string | null;
  created_at: string;
  updated_at: string;
  claimed_at: string | null;
  completed_at: string | null;
}

export interface DonationPage {
  items: Donation[];
  next_cursor: string | null;
}

export type DonationCursors = Record<string, string>;

export interface AuditEvent {
  id: string;
  entity_type: string;
  entity_id: string;
  event_type: string;
  actor_id: string;
  occurred_at: string;
  before_status: string | null;
  after_status: string | null;
  metadata: Record<string, string>;
  request_id: string | null;
}

export interface UserProfile {
  user_id: string;
  role: "donor" | "ngo" | "admin";
  status: "active" | "suspended";
  created_at: string;
  updated_at: string;
}

export interface Analytics {
  total_donations: number;
  completed_pickups: number;
  available_donations: number;
  claimed_donations: number;
  cancelled_donations: number;
  expired_donations: number;
  donors_registered: number | null;
  recipients_registered: number | null;
  active_users: number | null;
  claim_success_rate: number;
  completion_rate: number;
  expiry_rate: number;
  average_time_to_claim_seconds: number | null;
  quantities_by_status_and_unit: Record<DonationStatus, Record<string, number>>;
  completed_quantity_by_unit: Record<string, number>;
  category_counts: Record<string, number>;
  daily_donations: Record<string, number>;
  daily_completed_pickups: Record<string, number>;
  daily_completed_quantity_by_unit: Record<string, Record<string, number>>;
  daily_status_counts: Record<string, Partial<Record<DonationStatus, number>>>;
  last_updated: string;
  data_source: "local_live" | "cloud_live" | "etl_snapshot";
}

export interface UserDashboard {
  role: "donor" | "ngo";
  total_donations: number;
  available_donations: number;
  marketplace_available_donations: number;
  claimed_donations: number;
  completed_pickups: number;
  cancelled_donations: number;
  expired_donations: number;
  completed_quantity_by_unit: Record<string, number>;
  upcoming_pickups: Donation[];
  recent_donations: Donation[];
  recent_activity: AuditEvent[];
  last_updated: string;
  data_source: "local_live" | "cloud_live";
}

export interface ETLRun {
  run_id: string;
  status: "running" | "succeeded" | "failed";
  mode: "local" | "mocked_cloud" | "cloud";
  started_at: string;
  completed_at: string | null;
  processing_duration_seconds: number | null;
  input_records: number;
  total_clean_donations: number;
  rejected_records: number;
  duplicate_records: number;
  completed_pickups: number;
  error: string | null;
  reports: string[];
}

export interface SystemHealth {
  checked_at: string;
  api: "reachable";
  application_mode: string;
  database: {
    adapter: string;
    status: "healthy" | "unavailable";
    donation_count: number | null;
    error_type: string | null;
  };
  etl: ETLRun | null;
  ci: string;
  deployment: string;
}

const API_BASE = import.meta.env.VITE_API_BASE?.trim() ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");
const LOCAL_DEMO =
  import.meta.env.DEV &&
  import.meta.env.VITE_AUTH_MODE === "local-demo";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE) {
    throw new Error("VITE_API_BASE is required for a production build.");
  }
  let response: Response;
  try {
    const accessToken = LOCAL_DEMO ? null : await readAccessToken();
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(15_000),
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...init?.headers,
      },
    });
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "TimeoutError") {
      throw new Error("The API request timed out. Retry when the service is responsive.");
    }
    if (reason instanceof TypeError) {
      throw new Error("Cannot reach the API. Start the local backend and try again.");
    }
    throw reason;
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    const message = body?.detail ?? `Request failed (${response.status}).`;
    if (response.status === 401) {
      throw new Error(`Your session is not authorized. Sign in again. ${message}`);
    }
    if (response.status === 403) {
      throw new Error(`You do not have permission for this action. ${message}`);
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

async function download(path: string, filename: string): Promise<void> {
  if (!API_BASE) {
    throw new Error("VITE_API_BASE is required for a production build.");
  }
  let response: Response;
  try {
    const accessToken = LOCAL_DEMO ? null : await readAccessToken();
    response = await fetch(`${API_BASE}${path}`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      signal: AbortSignal.timeout(15_000),
    });
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "TimeoutError") {
      throw new Error("The download timed out. Retry when the service is responsive.");
    }
    if (reason instanceof TypeError) {
      throw new Error("Cannot reach the API. Start the local backend and try again.");
    }
    throw reason;
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(body?.detail ?? `Download failed (${response.status}).`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

export const api = {
  async listDonations(
    role: "donor" | "ngo" | "admin",
    actorId: string,
    statusFilter: string,
    cursors: DonationCursors = {},
  ): Promise<{ items: Donation[]; cursors: DonationCursors }> {
    const statusNames: DonationStatus[] = [
      "available",
      "claimed",
      "picked_up",
      "cancelled",
      "expired",
    ];
    const requests: Array<Promise<[string, DonationPage]>> = [];
    if (role === "admin") {
      const statuses = statusFilter
        ? [statusFilter as DonationStatus]
        : statusNames;
      for (const status of statuses) {
        const query = new URLSearchParams({ status, limit: "25" });
        if (cursors[status]) query.set("cursor", cursors[status]);
        if (LOCAL_DEMO) query.set("actor_id", actorId);
        requests.push(
          request<DonationPage>(`/api/donations/page?${query.toString()}`).then(
            (page) => [status, page],
          ),
        );
      }
    } else {
      if (!statusFilter || statusFilter === "available") {
        const query = new URLSearchParams({ status: "available", limit: "25" });
        if (cursors.available) query.set("cursor", cursors.available);
        requests.push(
          request<DonationPage>(`/api/donations/page?${query.toString()}`).then(
            (page) => ["available", page],
          ),
        );
      }
      if (role === "donor" || role === "ngo") {
        const query = new URLSearchParams({ limit: "25" });
        if (LOCAL_DEMO) query.set("actor_id", actorId);
        if (cursors.mine) query.set("cursor", cursors.mine);
        requests.push(
          request<DonationPage>(`/api/donations/mine?${query.toString()}`).then(
            (page) => ["mine", page],
          ),
        );
      }
    }

    const pages = await Promise.all(requests);
    const nextCursors = { ...cursors };
    pages.forEach(([key, page]) => {
      if (page.next_cursor) nextCursors[key] = page.next_cursor;
      else delete nextCursors[key];
    });
    const items = [...new Map(
      pages.flatMap(([, page]) => page.items).map((item) => [item.id, item]),
    ).values()].sort((left, right) =>
      right.created_at.localeCompare(left.created_at),
    );
    return { items, cursors: nextCursors };
  },
  createDonation: (donation: {
    donor_id: string;
    food_name: string;
    description?: string;
    category?: string;
    quantity: number;
    unit: string;
    available_at?: string | null;
    pickup_deadline: string;
    pickup_location?: string;
  }) =>
    request<Donation>("/api/donations", {
      method: "POST",
      body: JSON.stringify(
        LOCAL_DEMO
          ? donation
          : {
              food_name: donation.food_name,
              description: donation.description,
              category: donation.category,
              quantity: donation.quantity,
              unit: donation.unit,
              available_at: donation.available_at,
              pickup_deadline: donation.pickup_deadline,
              pickup_location: donation.pickup_location,
            },
      ),
    }),
  updateDonation: (
    id: string,
    actorId: string,
    donation: Omit<Donation, "id" | "donor_id" | "status" | "claimed_by" | "created_at" | "updated_at" | "claimed_at" | "completed_at">,
  ) =>
    request<Donation>(`/api/donations/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(
        LOCAL_DEMO ? { ...donation, actor_id: actorId } : donation,
      ),
    }),
  claimDonation: (id: string, ngoId: string) =>
    request<Donation>(`/api/donations/${id}/claim`, {
      method: "POST",
      body: JSON.stringify(LOCAL_DEMO ? { ngo_id: ngoId } : {}),
    }),
  updateStatus: (id: string, actorId: string, status: "cancelled" | "picked_up") =>
    request<Donation>(`/api/donations/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify(LOCAL_DEMO ? { actor_id: actorId, status } : { status }),
    }),
  analytics: (actorId: string, filters: Record<string, string> = {}) => {
    const query = new URLSearchParams();
    if (LOCAL_DEMO) query.set("actor_id", actorId);
    Object.entries(filters).forEach(([key, value]) => {
      if (value) query.set(key, value);
    });
    return request<Analytics>(
      `/api/admin/analytics?${query.toString()}`,
    );
  },
  dashboard: (actorId: string) =>
    request<UserDashboard>(
      `/api/me/dashboard?actor_id=${encodeURIComponent(actorId)}`,
    ),
  adminUsers: (
    actorId: string,
    search: string,
    status = "",
    cursor?: string,
  ) => {
    const query = new URLSearchParams({
      actor_id: actorId,
      search,
      limit: "25",
    });
    if (status) query.set("status", status);
    if (cursor) query.set("cursor", cursor);
    return request<{ items: UserProfile[]; next_cursor: string | null }>(
      `/api/admin/users?${query.toString()}`,
    );
  },
  setUserStatus: (actorId: string, userId: string, status: "active" | "suspended") =>
    request<UserProfile>(`/api/admin/users/${encodeURIComponent(userId)}/status`, {
      method: "PATCH",
      body: JSON.stringify({ actor_id: actorId, status }),
    }),
  donationEvents: (actorId: string, donationId: string, cursor?: string) =>
    request<{ items: AuditEvent[]; next_cursor: string | null }>(
      `/api/donations/${encodeURIComponent(donationId)}/events?${new URLSearchParams({
        ...(LOCAL_DEMO ? { actor_id: actorId } : {}),
        ...(cursor ? { cursor } : {}),
        limit: "25",
      }).toString()}`,
    ),
  userEvents: (actorId: string, userId: string, cursor?: string) => {
    const query = new URLSearchParams({
      actor_id: actorId,
      limit: "25",
    });
    if (cursor) query.set("cursor", cursor);
    return request<{ items: AuditEvent[]; next_cursor: string | null }>(
      `/api/admin/users/${encodeURIComponent(userId)}/events?${query.toString()}`,
    );
  },
  adminActivity: (
    actorId: string,
    options: {
      cursor?: string;
      eventType?: string;
      startDate?: string;
      endDate?: string;
    } = {},
  ) => {
    const query = new URLSearchParams({ actor_id: actorId, limit: "25" });
    if (options.cursor) query.set("cursor", options.cursor);
    if (options.eventType) query.set("event_type", options.eventType);
    if (options.startDate) query.set("start_date", options.startDate);
    if (options.endDate) query.set("end_date", options.endDate);
    return request<{ items: AuditEvent[]; next_cursor: string | null }>(
      `/api/admin/activity?${query.toString()}`,
    );
  },
  expireDonations: (actorId: string) =>
    request<{ expired_count: number }>(
      `/api/admin/expire?actor_id=${encodeURIComponent(actorId)}`,
      { method: "POST" },
    ),
  listETLRuns: (actorId: string) =>
    request<{ items: ETLRun[]; mode: "local" }>(
      `/api/admin/etl/runs?actor_id=${encodeURIComponent(actorId)}`,
    ),
  runETL: (actorId: string) =>
    request<ETLRun>(
      `/api/admin/etl/runs?actor_id=${encodeURIComponent(actorId)}`,
      { method: "POST" },
    ),
  downloadETLReport: (actorId: string, runId: string, reportName: string) =>
    download(
      `/api/admin/etl/runs/${encodeURIComponent(runId)}/reports/${encodeURIComponent(reportName)}?actor_id=${encodeURIComponent(actorId)}`,
      reportName,
    ),
  downloadApplicationExport: (actorId: string) =>
    download(
      `/api/admin/export?actor_id=${encodeURIComponent(actorId)}`,
      "donations-export.json",
    ),
  systemHealth: (actorId: string) =>
    request<SystemHealth>(
      `/api/admin/system/health?actor_id=${encodeURIComponent(actorId)}`,
    ),
};
