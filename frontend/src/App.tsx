import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Activity,
  Boxes,
  CalendarClock,
  Check,
  Clock3,
  Database,
  Download,
  History,
  CircleAlert,
  CircleX,
  HeartHandshake,
  Leaf,
  LoaderCircle,
  Menu,
  PackageCheck,
  Plus,
  RotateCw,
  ShoppingBasket,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Utensils,
  Users,
} from "lucide-react";
import {
  Analytics,
  api,
  AuditEvent,
  Donation,
  DonationCursors,
  ETLRun,
  SystemHealth,
  UserDashboard,
  UserProfile,
} from "./api";
import {
  beginSignIn,
  beginSignOut,
  cognitoConfigured,
  cognitoMode,
  completeSignIn,
  getSignedInUser,
  localDemoEnabled,
  userRole,
} from "./auth";
import { User } from "oidc-client-ts";

type DemoIdentity = {
  id: string;
  label: string;
  role: "donor" | "ngo" | "admin";
};

type PageKey =
  | "overview"
  | "create"
  | "browse"
  | "donations"
  | "claims"
  | "history"
  | "users"
  | "activity"
  | "analytics"
  | "etl"
  | "reports"
  | "audit"
  | "health"
  | "profile"
  | "detail";

type NavItem = { key: PageKey; label: string; caption: string };
type PendingConfirmation = {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
};

const navigation: Record<DemoIdentity["role"], NavItem[]> = {
  donor: [
    { key: "overview", label: "Overview", caption: "Your impact" },
    { key: "create", label: "Create donation", caption: "Share surplus food" },
    { key: "donations", label: "My donations", caption: "Manage listings" },
    { key: "claims", label: "Claims", caption: "Awaiting collection" },
    { key: "history", label: "Donation history", caption: "Completed & closed" },
    { key: "profile", label: "My profile", caption: "Account details" },
  ],
  ngo: [
    { key: "overview", label: "Overview", caption: "Your collections" },
    { key: "browse", label: "Browse food", caption: "Available nearby" },
    { key: "claims", label: "Active claims", caption: "Plan collections" },
    { key: "history", label: "Collection history", caption: "Completed & closed" },
    { key: "profile", label: "My profile", caption: "Organization account" },
  ],
  admin: [
    { key: "overview", label: "Overview", caption: "Platform snapshot" },
    { key: "users", label: "User management", caption: "Local demo profiles" },
    { key: "donations", label: "All donations", caption: "Lifecycle records" },
    { key: "activity", label: "Claims & activity", caption: "Progress and recent events" },
    { key: "analytics", label: "Analytics", caption: "Metrics & trends" },
    { key: "etl", label: "ETL control center", caption: "Run local pipeline" },
    { key: "reports", label: "Reports & exports", caption: "Download outputs" },
    { key: "audit", label: "Audit history", caption: "Application events" },
    { key: "health", label: "System health", caption: "Verified local status" },
    { key: "profile", label: "My profile", caption: "Account details" },
  ],
};

const pageTitles: Record<PageKey, string> = {
  overview: "Overview",
  create: "Create a donation",
  browse: "Food marketplace",
  donations: "Donation listings",
  claims: "Claims and collections",
  history: "Donation history",
  users: "User management",
  activity: "Claims and activity",
  analytics: "Platform analytics",
  etl: "ETL control center",
  reports: "Reports and exports",
  audit: "Audit history",
  health: "System health",
  profile: "My profile",
  detail: "Donation details",
};

const localDemoBuild = import.meta.env.DEV && import.meta.env.VITE_AUTH_MODE === "local-demo";
const identities: DemoIdentity[] = localDemoBuild
  ? [
      { id: "donor-demo", label: "Ananya Raman · Donor", role: "donor" },
      { id: "donor-demo-2", label: "Arjun Kumar · Donor", role: "donor" },
      { id: "ngo-demo", label: "Meera Foundation · Recipient", role: "ngo" },
      { id: "ngo-demo-2", label: "Community Kitchen Network · Recipient", role: "ngo" },
      { id: "admin-demo", label: "ShareBite Operations · Admin", role: "admin" },
    ]
  : [];

const identityNames: Record<string, string> = localDemoBuild
  ? {
      "donor-demo": "Ananya Raman",
      "donor-demo-2": "Arjun Kumar",
      "ngo-demo": "Meera Foundation",
      "ngo-demo-2": "Community Kitchen Network",
      "admin-demo": "ShareBite Operations",
    }
  : {};

function displayIdentityName(userId: string | null) {
  if (!userId) return "Not claimed";
  return identityNames[userId] ?? (userId.startsWith("system:") ? "System" : "Account");
}

function localDateTimeValue(hoursFromNow: number) {
  const date = new Date(Date.now() + hoursFromNow * 60 * 60 * 1000);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function localDateTimeValueFrom(value: string) {
  const date = new Date(value);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function formatDeadline(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function statusDistribution(metrics: Analytics): Record<string, number> {
  return Object.values(metrics.daily_status_counts).reduce<Record<string, number>>(
    (totals, dailyCounts) => {
      Object.entries(dailyCounts).forEach(([status, count]) => {
        totals[status] = (totals[status] ?? 0) + (count ?? 0);
      });
      return totals;
    },
    {},
  );
}

function formatQuantityByUnit(quantities: Record<string, number>) {
  return Object.entries(quantities)
    .map(([unit, amount]) => `${amount.toLocaleString()} ${unit}`)
    .join(" · ");
}

function describeEvent(eventType: string) {
  return eventType.replace(/_/g, " ");
}

function App() {
  const [identityId, setIdentityId] = useState(
    localDemoEnabled ? "donor-demo" : "",
  );
  const [signedInUser, setSignedInUser] = useState<User | null>(null);
  const [authMessage, setAuthMessage] = useState("");
  const [authBusy, setAuthBusy] = useState(!localDemoEnabled);
  const [donations, setDonations] = useState<Donation[]>([]);
  const [donationCursors, setDonationCursors] = useState<DonationCursors>({});
  const [metrics, setMetrics] = useState<Analytics | null>(null);
  const [dashboard, setDashboard] = useState<UserDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState<PendingConfirmation | null>(null);
  const [foodName, setFoodName] = useState("");
  const [quantity, setQuantity] = useState("10");
  const [unit, setUnit] = useState("portions");
  const [deadline, setDeadline] = useState(() => localDateTimeValue(24));
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("other");
  const [pickupLocation, setPickupLocation] = useState("");
  const [editingDonation, setEditingDonation] = useState<Donation | null>(null);
  const [donationSearch, setDonationSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [userStatusFilter, setUserStatusFilter] = useState("");
  const [userRoleFilter, setUserRoleFilter] = useState("");
  const [analyticsStart, setAnalyticsStart] = useState("");
  const [analyticsEnd, setAnalyticsEnd] = useState("");
  const [analyticsCategory, setAnalyticsCategory] = useState("");
  const [analyticsLocation, setAnalyticsLocation] = useState("");
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [userCursor, setUserCursor] = useState<string | null>(null);
  const visibleUsers = users.filter((user) =>
    displayIdentityName(user.user_id).toLocaleLowerCase().includes(userSearch.trim().toLocaleLowerCase()) &&
    (!userRoleFilter || user.role === userRoleFilter),
  );
  const [timelineId, setTimelineId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<AuditEvent[]>([]);
  const [timelineCursor, setTimelineCursor] = useState<string | null>(null);
  const [activePage, setActivePage] = useState<PageKey>("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [locationFilter, setLocationFilter] = useState("");
  const [deadlineFilter, setDeadlineFilter] = useState("");
  const [sortOrder, setSortOrder] = useState<"newest" | "deadline">("newest");
  const [etlRuns, setEtlRuns] = useState<ETLRun[]>([]);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [adminActivity, setAdminActivity] = useState<AuditEvent[]>([]);
  const [activityCursor, setActivityCursor] = useState<string | null>(null);
  const [activityType, setActivityType] = useState("");
  const [activityStart, setActivityStart] = useState("");
  const [activityEnd, setActivityEnd] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedDonationId, setSelectedDonationId] = useState<string | null>(null);
  const [userActivity, setUserActivity] = useState<AuditEvent[]>([]);

  const identity = useMemo(() => {
    if (localDemoEnabled) {
      return identities.find((item) => item.id === identityId) ?? identities[0];
    }
    if (!signedInUser) return null;
    const role = userRole(signedInUser);
    if (!role || typeof signedInUser.profile.sub !== "string") return null;
    return {
      id: signedInUser.profile.sub,
      label: typeof signedInUser.profile.name === "string"
        ? signedInUser.profile.name
        : role === "admin" ? "Administrator" : role === "ngo" ? "Recipient organization" : "Donor account",
      role,
    };
  }, [identityId, signedInUser]);

  useEffect(() => {
    setActivePage("overview");
    setStatusFilter("");
    setMobileNavOpen(false);
    setSelectedUserId(null);
    setSelectedDonationId(null);
    setUserActivity([]);
  }, [identity?.id, identity?.role]);

  useEffect(() => {
    if (localDemoEnabled) return;
    if (!cognitoMode) {
      setAuthMessage("Local demo identities are available only in the Vite development server. Configure Cognito OIDC for this build.");
      setAuthBusy(false);
      return;
    }
    if (!cognitoConfigured) {
      setAuthMessage("Cognito login is not configured. Set the issuer and public app-client ID from a reviewed deployment.");
      setAuthBusy(false);
      return;
    }
    let active = true;
    const loadUser = async () => {
      try {
        const user = window.location.pathname === "/auth/callback"
          ? await completeSignIn()
          : await getSignedInUser();
        if (!active) return;
        if (window.location.pathname === "/auth/callback") {
          window.history.replaceState({}, document.title, "/");
        }
        setSignedInUser(user);
      } catch (reason) {
        if (active) {
          setAuthMessage(reason instanceof Error ? reason.message : "Cognito sign-in could not be completed.");
        }
      } finally {
        if (active) setAuthBusy(false);
      }
    };
    void loadUser();
    return () => {
      active = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    setError("");
    if (!identity) {
      setDonations([]);
      setDonationCursors({});
      setMetrics(null);
      setDashboard(null);
      setUsers([]);
      setUserCursor(null);
      setLoading(false);
      return;
    }
    try {
      const [currentPage, userDashboard] = await Promise.all([
        api.listDonations(identity.role, identity.id, statusFilter),
        identity.role !== "admin"
          ? api.dashboard(identity.id)
          : Promise.resolve(null),
      ]);
      setDonations(currentPage.items);
      setDonationCursors(currentPage.cursors);
      setDashboard(userDashboard);
      if (identity.role === "admin") {
        const [currentMetrics, userPage] = await Promise.all([
          api.analytics(identity.id, {
            start_date: analyticsStart,
            end_date: analyticsEnd,
            status: statusFilter,
            category: analyticsCategory,
            location: analyticsLocation,
          }),
          localDemoEnabled
            ? api.adminUsers(identity.id, "", userStatusFilter)
            : Promise.resolve({ items: [], next_cursor: null }),
        ]);
        setMetrics(currentMetrics);
        setUsers(userPage.items);
        setUserCursor(localDemoEnabled ? userPage.next_cursor : null);
        if (localDemoEnabled) {
          const [activityPage, runPage, currentHealth] = await Promise.all([
            activePage === "overview" || activePage === "activity" || activePage === "audit"
              ? api.adminActivity(identity.id, {
                  eventType: activityType,
                  startDate: activityStart,
                  endDate: activityEnd,
                })
              : Promise.resolve(null),
            activePage === "overview" || activePage === "etl" || activePage === "reports"
              ? api.listETLRuns(identity.id)
              : Promise.resolve(null),
            activePage === "health"
              ? api.systemHealth(identity.id)
              : Promise.resolve(null),
          ]);
          if (activityPage) {
            setAdminActivity(activityPage.items);
            setActivityCursor(activityPage.next_cursor);
          }
          if (runPage) setEtlRuns(runPage.items);
          if (currentHealth) setHealth(currentHealth);
        }
      } else {
        setMetrics(null);
        setUsers([]);
        setUserCursor(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load donations.");
    } finally {
      setLoading(false);
    }
  }, [
    analyticsCategory,
    analyticsEnd,
    analyticsLocation,
    analyticsStart,
    activePage,
    activityEnd,
    activityStart,
    activityType,
    identity?.id,
    identity?.role,
    statusFilter,
    userStatusFilter,
  ]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!identity || localDemoEnabled) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 8_000);
    return () => window.clearInterval(interval);
  }, [identity, refresh]);

  useEffect(() => {
    if (!confirmation) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) setConfirmation(null);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [busy, confirmation]);

  async function perform(
    action: () => Promise<unknown>,
    successMessage: string,
  ): Promise<boolean> {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(successMessage);
      await refresh();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The action could not be completed.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function performAuth(action: () => Promise<void>, fallback: string) {
    setAuthMessage("");
    try {
      await action();
    } catch (reason) {
      setAuthMessage(reason instanceof Error ? reason.message : fallback);
    }
  }

  async function runETL() {
    if (!identity || identity.role !== "admin" || !localDemoEnabled) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const run = await api.runETL(identity.id);
      setEtlRuns((current) => [run, ...current.filter((item) => item.run_id !== run.run_id)]);
      setNotice(
        `ETL ${run.status}: ${run.total_clean_donations} clean, ${run.rejected_records} rejected, ${run.duplicate_records} duplicates.`,
      );
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The local ETL run could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport(runId: string, reportName: string) {
    if (!identity || identity.role !== "admin") return;
    setError("");
    try {
      await api.downloadETLReport(identity.id, runId, reportName);
      setNotice(`${reportName} downloaded.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The report could not be downloaded.");
    }
  }

  async function downloadApplicationExport() {
    if (!identity || identity.role !== "admin") return;
    setError("");
    try {
      await api.downloadApplicationExport(identity.id);
      setNotice("Application export downloaded.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The application export could not be downloaded.");
    }
  }

  async function loadUserActivity(userId: string) {
    if (!identity || identity.role !== "admin" || !localDemoEnabled) return;
    setSelectedUserId(userId);
    setError("");
    try {
      const result = await api.userEvents(identity.id, userId);
      setUserActivity(result.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load user activity.");
    }
  }

  async function loadMoreActivity() {
    if (!identity || identity.role !== "admin" || !activityCursor || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.adminActivity(identity.id, {
        cursor: activityCursor,
        eventType: activityType,
        startDate: activityStart,
        endDate: activityEnd,
      });
      setAdminActivity((current) => [...current, ...result.items]);
      setActivityCursor(result.next_cursor);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load more audit events.");
    } finally {
      setBusy(false);
    }
  }

  async function createDonation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (identity?.role !== "donor") return;
    const created = await perform(
      () =>
        api.createDonation({
          donor_id: identity.id,
          food_name: foodName.trim(),
          description: description.trim(),
          category,
          quantity: Number(quantity),
          unit: unit.trim(),
          pickup_deadline: new Date(deadline).toISOString(),
          pickup_location: pickupLocation.trim(),
        }),
      "Your donation is now listed for pickup.",
    );
    if (created) {
      setFoodName("");
      setDescription("");
      setPickupLocation("");
    }
  }

  async function saveDonationEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!identity || identity.role !== "donor" || !editingDonation) return;
    const updated = await perform(
      () => api.updateDonation(editingDonation.id, identity.id, {
        food_name: editingDonation.food_name.trim(),
        description: editingDonation.description.trim(),
        category: editingDonation.category,
        quantity: Number(editingDonation.quantity),
        unit: editingDonation.unit.trim(),
        available_at: editingDonation.available_at,
        pickup_deadline: new Date(editingDonation.pickup_deadline).toISOString(),
        pickup_location: editingDonation.pickup_location.trim(),
      }),
      "Donation details updated.",
    );
    if (updated) setEditingDonation(null);
  }

  function canClaim(donation: Donation) {
    return identity?.role === "ngo" &&
      donation.status === "available" &&
      new Date(donation.pickup_deadline).getTime() > Date.now();
  }

  function canConfirmPickup(donation: Donation) {
    return (
      donation.status === "claimed" &&
      (
        (identity?.role === "ngo" && donation.claimed_by === identity.id) ||
        (localDemoEnabled && identity?.role === "admin")
      )
    );
  }

  function canCancel(donation: Donation) {
    return (
      donation.status === "available" &&
      (
        (identity?.role === "donor" && donation.donor_id === identity.id) ||
        (localDemoEnabled && identity?.role === "admin")
      )
    );
  }

  const selectedDonation = donations.find((item) => item.id === selectedDonationId);
  const visibleDonations = donations.filter((donation) => {
    const matchesSearch = `${donation.food_name} ${donation.description} ${donation.pickup_location}`
      .toLocaleLowerCase()
      .includes(donationSearch.toLocaleLowerCase());
    const matchesStatus = !statusFilter || donation.status === statusFilter;
    const matchesCategory = !categoryFilter || donation.category === categoryFilter;
    const matchesLocation = !locationFilter ||
      donation.pickup_location.toLocaleLowerCase().includes(locationFilter.toLocaleLowerCase());
    const matchesDeadline = !deadlineFilter || donation.pickup_deadline.slice(0, 10) <= deadlineFilter;
    const matchesOwner = identity?.role !== "donor" ||
      !["donations", "claims", "history"].includes(activePage) ||
      donation.donor_id === identity.id;
    const matchesClaimant = identity?.role !== "ngo" ||
      !["claims", "history"].includes(activePage) ||
      donation.claimed_by === identity.id;
    const matchesPage =
      activePage !== "history" ||
      donation.status === "picked_up" ||
      donation.status === "cancelled" ||
      donation.status === "expired";
    return matchesSearch && matchesStatus && matchesCategory && matchesLocation &&
      matchesDeadline && matchesOwner && matchesClaimant && matchesPage;
  }).sort((left, right) => sortOrder === "deadline"
    ? left.pickup_deadline.localeCompare(right.pickup_deadline)
    : right.created_at.localeCompare(left.created_at));

  const showDonationList = Boolean(identity) && (
    activePage === "overview" ||
    activePage === "browse" ||
    activePage === "donations" ||
    activePage === "claims" ||
    (activePage === "activity" && identity?.role === "admin") ||
    activePage === "history"
  );
  const showSidePanel = Boolean(identity) && (
    identity?.role !== "admin" &&
    (activePage === "overview" ||
      activePage === "browse" ||
      activePage === "create")
  );

  function navigateTo(page: PageKey) {
    setActivePage(page);
    setMobileNavOpen(false);
    setDonationSearch("");
    setCategoryFilter("");
    setLocationFilter("");
    setDeadlineFilter("");
    setStatusFilter(
      page === "browse"
        ? "available"
        : page === "claims" || page === "activity"
          ? "claimed"
          : "",
    );
    if (page !== "detail") {
      setTimelineId(null);
      setTimeline([]);
      setTimelineCursor(null);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function pageDescription() {
    if (activePage === "overview" && identity?.role === "donor") {
      return "Manage your listings and see where shared food is making a difference.";
    }
    if (activePage === "overview" && identity?.role === "ngo") {
      return "Find available food, manage your reservations, and track completed collections.";
    }
    if (activePage === "overview" && identity?.role === "admin") {
      return "Monitor donation activity, operational exceptions, and the latest local data-quality run.";
    }
    if (activePage === "browse") return "Browse available donations and reserve one for your community.";
    if (activePage === "claims") return "Review currently claimed donations and confirm completed pickups.";
    if (activePage === "activity") return "Review active claims and recent recorded platform events.";
    if (activePage === "history") return "Completed, cancelled, and expired records visible to this identity.";
    if (activePage === "users") return "Manage synthetic local demo profiles. This is not Cognito user administration.";
    if (activePage === "etl") return "Run the real Pandas transformation against a bounded export of local application records.";
    if (activePage === "reports") return "Download reports produced by local ETL runs or export the application records.";
    if (activePage === "audit") return "Review persisted application events from the local SQLite database.";
    if (activePage === "health") return "Live local API and database checks. CI and cloud deployment are reported separately.";
    if (activePage === "profile") return "Review the identity and access mode used for this session.";
    return "Review current application records and verified metrics.";
  }

  function selectNavigationPage(page: PageKey) {
    navigateTo(page);
  }

  async function showTimeline(donationId: string) {
    if (!identity) return;
    setError("");
    try {
      const result = await api.donationEvents(identity.id, donationId);
      setTimelineId(donationId);
      setTimeline(result.items);
      setTimelineCursor(result.next_cursor);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load donation history.");
    }
  }

  async function loadMoreHistory() {
    if (!identity || !timelineId || !timelineCursor || busy) return;
    setBusy(true);
    setError("");
    try {
      const page = await api.donationEvents(identity.id, timelineId, timelineCursor);
      setTimeline((current) => [...current, ...page.items]);
      setTimelineCursor(page.next_cursor);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load more history.");
    } finally {
      setBusy(false);
    }
  }

  async function loadMoreDonations() {
    if (!identity || loading || busy) return;
    setBusy(true);
    setError("");
    try {
      const page = await api.listDonations(
        identity.role,
        identity.id,
        statusFilter,
        donationCursors,
      );
      setDonations((current) =>
        [...new Map([...current, ...page.items].map((item) => [item.id, item])).values()]
          .sort((left, right) => right.created_at.localeCompare(left.created_at)),
      );
      setDonationCursors(page.cursors);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load more donations.");
    } finally {
      setBusy(false);
    }
  }

  async function loadMoreUsers() {
    if (!identity || identity.role !== "admin" || !userCursor || busy) return;
    setBusy(true);
    setError("");
    try {
      const page = await api.adminUsers(identity.id, "", userStatusFilter, userCursor);
      setUsers((current) => [...current, ...page.items]);
      setUserCursor(page.next_cursor);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load more demo users.");
    } finally {
      setBusy(false);
    }
  }

  async function updateUserStatus(user: UserProfile) {
    const userName = displayIdentityName(user.user_id);
    if (!identity) return;
    await perform(
      () => api.setUserStatus(identity.id, user.user_id, user.status === "active" ? "suspended" : "active"),
      `${userName} is now ${user.status === "active" ? "suspended" : "active"}.`,
    );
  }

  function confirmUserStatusChange(user: UserProfile) {
    const nextStatus = user.status === "active" ? "suspended" : "active";
    const userName = displayIdentityName(user.user_id);
    setConfirmation({
      title: `${nextStatus === "suspended" ? "Suspend" : "Reactivate"} account?`,
      message: `${userName} will ${nextStatus === "suspended" ? "no longer be able to use" : "regain access to"} this local demo account.`,
      confirmLabel: nextStatus === "suspended" ? "Suspend account" : "Reactivate account",
      onConfirm: () => void updateUserStatus(user),
    });
  }

  function openDonationQueue(status = "") {
    navigateTo("donations");
    setStatusFilter(status);
  }

  function openDonationDetails(donation: Donation) {
    if (!identity) return;
    setSelectedDonationId(donation.id);
    setTimelineId(null);
    setTimeline([]);
    setTimelineCursor(null);
    setActivePage("detail");
    if (
      identity.role === "admin" ||
      donation.donor_id === identity.id ||
      donation.claimed_by === identity.id
    ) void showTimeline(donation.id);
  }

  return (
    <main className="page-shell portal-shell-root">
      <header className="topbar">
        <a className="brand" href="#" aria-label="ShareBite home">
          <span className="brand-mark"><Leaf size={19} strokeWidth={2.5} /></span>
          <span>ShareBite<span className="brand-period">.</span></span>
        </a>
        <div className="header-context">
          <span className="header-kicker">COMMUNITY FOOD NETWORK</span>
          <strong>{identity?.role === "admin" && activePage === "overview" ? "Operations overview" : identity ? pageTitles[activePage] : "Local food exchange"}</strong>
        </div>
        <button
          className="mobile-menu-button"
          type="button"
          aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={mobileNavOpen}
          onClick={() => setMobileNavOpen((open) => !open)}
        >
          <Menu size={19} />
        </button>
        {localDemoEnabled ? (
          <label className="identity-picker">
            <ShieldCheck size={16} aria-hidden="true" />
            <span className="sr-only">Local account</span>
            <select
              value={identityId}
              onChange={(event) => {
                setIdentityId(event.target.value);
                setLoading(true);
              }}
            >
              {identities.map((item) => (
                <option value={item.id} key={item.id}>{item.label}</option>
              ))}
            </select>
          </label>
        ) : identity ? (
          <>
            <span className="account-label">{identity.label}</span>
            <button className="button button-quiet" onClick={() => void performAuth(beginSignOut, "Sign out could not be completed.")}>
              Sign out
            </button>
          </>
        ) : cognitoMode && cognitoConfigured ? (
          <button className="button button-primary" disabled={authBusy} onClick={() => void performAuth(beginSignIn, "Sign in could not be started.")}>
            Sign in / register
          </button>
        ) : null}
      </header>

      <div className={`portal-layout ${mobileNavOpen ? "portal-nav-open" : ""}`}>
      {identity && (
        <>
        <button
          className="sidebar-backdrop"
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileNavOpen(false)}
        />
        <aside className="portal-sidebar">
          <div className="sidebar-label">WORKSPACE</div>
          <div className="sidebar-identity">
            <span className={`identity-avatar avatar-${identity.role}`}>
              {identity.role === "admin" ? <ShieldCheck size={17} /> : identity.role === "ngo" ? <HeartHandshake size={17} /> : <Leaf size={17} />}
            </span>
            <span><strong>{identity.role === "admin" ? "Administrator" : identity.role === "ngo" ? "NGO partner" : "Food donor"}</strong><small>{identity.label}</small></span>
          </div>
          <nav className="portal-nav" aria-label={`${identity.role} portal navigation`}>
            {navigation[identity.role].map((item) => (
              <button
                type="button"
                key={item.key}
                className={`portal-nav-item ${activePage === item.key ? "portal-nav-active" : ""}`}
                onClick={() => selectNavigationPage(item.key)}
              >
                <span className="nav-item-copy"><strong>{item.label}</strong><small>{item.caption}</small></span>
                <ArrowUpRight size={14} aria-hidden="true" />
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <span className="sidebar-status-dot" />
            <span>{localDemoEnabled ? "Local demo workspace" : "Authenticated session"}</span>
          </div>
        </aside>
        </>
      )}
      <div className="portal-main">
      {activePage === "overview" && identity?.role !== "admin" && <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow"><Sparkles size={14} /> GOOD FOOD. GOOD NEIGHBOURS.</div>
          <h1>Share a little.<br /><span>Change a lot.</span></h1>
          <p>Give surplus food a second chance. Connect with local kitchens and help good food find a good home.</p>
          <a className="hero-link" href="#exchange">Explore the exchange <ArrowDownRight size={17} /></a>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="sun-shape" />
          <div className="art-note"><span className="note-icon"><HeartHandshake size={18} /></span><span><strong>Good things grow</strong><small>when we share.</small></span></div>
          <div className="food-bowl"><div className="bowl-leaf leaf-one" /><div className="bowl-leaf leaf-two" /><div className="bowl-leaf leaf-three" /><div className="bowl-body" /></div>
          <div className="art-dot dot-one" /><div className="art-dot dot-two" /><div className="art-dot dot-three" />
        </div>
      </section>}

      {identity && activePage === "overview" && identity.role !== "admin" && <section className="impact-strip" aria-label="Community impact">
        <div className="impact-intro"><span className="impact-icon"><HeartHandshake size={19} /></span><span><strong>{identity.role === "ngo" ? "Your collections" : "Your shared food"}</strong><small>Live values from the connected application data.</small></span></div>
        <div className="impact-stat"><span className="stat-number">{identity.role === "ngo" ? dashboard?.marketplace_available_donations ?? "—" : dashboard?.total_donations ?? "—"}</span><span className="stat-label">{identity.role === "ngo" ? "available to claim" : "your donations"}</span></div>
        <div className="impact-stat"><span className="stat-number">{identity.role === "ngo" ? dashboard?.claimed_donations ?? "—" : dashboard?.available_donations ?? "—"}</span><span className="stat-label">{identity.role === "ngo" ? "active claims" : "currently available"}</span></div>
        <div className="impact-stat"><span className="stat-number">{dashboard?.completed_pickups ?? "—"}</span><span className="stat-label">completed pickups</span></div>
      </section>}

      <section className="exchange-section" id="exchange">
        <div className="section-heading">
          <div>
            <div className="eyebrow">{identity ? `${identity.role.toUpperCase()} PORTAL` : "THE COMMUNITY EXCHANGE"}</div>
            <h2>{identity?.role === "admin" && activePage === "overview" ? "Operations Overview" : identity ? pageTitles[activePage] : <>Good food, <em>going places.</em></>}</h2>
            <p>{identity ? pageDescription() : "Freshly shared by neighbours, ready for a new table."}</p>
          </div>
          <button className="button button-quiet" onClick={() => void refresh()} disabled={loading || busy}>
            <RotateCw size={15} className={loading ? "spin" : ""} /> Refresh
          </button>
        </div>

        <div className="demo-banner">
          <span className="demo-dot" />
          <span><strong>{localDemoEnabled ? "Local data mode" : "Authenticated application"}</strong> · {localDemoEnabled ? "Synthetic records and local-only identities; not production authentication." : "Identity and roles come from verified Cognito claims."}</span>
        </div>

        {!localDemoEnabled && !identity && (
          <div className="feedback feedback-error" role="status">
            <CircleAlert size={18} />{authBusy ? "Checking sign-in status…" : signedInUser ? "This account does not have exactly one authorized application role. Contact an administrator." : authMessage || "Sign in with an authorized account to continue."}
          </div>
        )}
        {authMessage && identity && (
          <div className="feedback feedback-error" role="alert"><CircleAlert size={18} />{authMessage}</div>
        )}
        {error && <div className="feedback feedback-error" role="alert"><CircleAlert size={18} />{error}</div>}
        {notice && <div className="feedback feedback-success" role="status"><Check size={18} />{notice}</div>}

        {identity?.role === "admin" && activePage === "overview" && (
          <section className="admin-overview" aria-label="Operations overview">
            <div className="admin-overview-toolbar">
              <div>
                <span className="eyebrow">OPERATIONAL SNAPSHOT</span>
                <p>{metrics?.data_source === "local_live" ? "Metrics from the connected local application database." : "Metrics from the authenticated application adapter."}</p>
              </div>
              <div className="admin-updated">
                <span>Last updated</span>
                <strong>{metrics ? new Date(metrics.last_updated).toLocaleString() : "Waiting for data"}</strong>
              </div>
            </div>
            <div className="workspace-filters admin-date-filters">
              <label><span className="field-label">Created from (UTC)</span><input type="date" value={analyticsStart} onChange={(event) => setAnalyticsStart(event.target.value)} /></label>
              <label><span className="field-label">Created through (UTC)</span><input type="date" value={analyticsEnd} onChange={(event) => setAnalyticsEnd(event.target.value)} /></label>
              <button className="text-button" disabled={!analyticsStart && !analyticsEnd} onClick={() => {
                setAnalyticsStart("");
                setAnalyticsEnd("");
              }}>Clear date range</button>
            </div>
            {metrics ? (
              <>
                <div className="admin-kpi-grid">
                  <button className="admin-kpi" onClick={() => openDonationQueue()} aria-label={`View all ${metrics.total_donations} donation records`}>
                    <span className="kpi-icon kpi-icon-neutral"><Boxes size={17} /></span><span className="kpi-label">Total donations</span><strong>{metrics.total_donations.toLocaleString()}</strong><small>In the selected creation-date range</small>
                  </button>
                  <button className="admin-kpi" onClick={() => openDonationQueue("available")} aria-label={`View ${metrics.available_donations} available donations`}>
                    <span className="kpi-icon kpi-icon-available"><ShoppingBasket size={17} /></span><span className="kpi-label">Available now</span><strong>{metrics.available_donations.toLocaleString()}</strong><small>Listing state and pickup deadline are current</small>
                  </button>
                  <button className="admin-kpi" onClick={() => openDonationQueue("claimed")} aria-label={`View ${metrics.claimed_donations} claimed donations`}>
                    <span className="kpi-icon kpi-icon-claimed"><Clock3 size={17} /></span><span className="kpi-label">Claimed</span><strong>{metrics.claimed_donations.toLocaleString()}</strong><small>Awaiting collection confirmation</small>
                  </button>
                  <button className="admin-kpi" onClick={() => openDonationQueue("picked_up")} aria-label={`View ${metrics.completed_pickups} completed pickups`}>
                    <span className="kpi-icon kpi-icon-complete"><PackageCheck size={17} /></span><span className="kpi-label">Completed pickups</span><strong>{metrics.completed_pickups.toLocaleString()}</strong><small>Confirmed through the application</small>
                  </button>
                  <button className="admin-kpi" onClick={() => openDonationQueue("expired")} aria-label={`View ${metrics.expired_donations} expired donations`}>
                    <span className="kpi-icon kpi-icon-warning"><TriangleAlert size={17} /></span><span className="kpi-label">Expired</span><strong>{metrics.expired_donations.toLocaleString()}</strong><small>{metrics.cancelled_donations.toLocaleString()} cancelled records</small>
                  </button>
                  <button className="admin-kpi" onClick={() => navigateTo("analytics")} aria-label="View completed redistribution quantities in analytics">
                    <span className="kpi-icon kpi-icon-neutral"><HeartHandshake size={17} /></span><span className="kpi-label">Redistributed</span><strong className="kpi-quantity">{formatQuantityByUnit(metrics.completed_quantity_by_unit) || "—"}</strong><small>Completed quantities grouped by original unit</small>
                  </button>
                </div>
                <div className="admin-insights-grid">
                  <section className="admin-insight-panel">
                    <div className="admin-insight-heading"><div><h3>Donation activity</h3><p>Records by creation date (UTC) · filtered range</p></div><button className="text-button" onClick={() => navigateTo("analytics")}>Full analytics</button></div>
                    <div className="compact-chart">
                      {Object.entries(metrics.daily_donations).slice(-7).map(([day, count]) => (
                        <div className="chart-row" key={day}>
                          <span>{day.slice(5)}</span><div className="chart-track"><span style={{ width: `${Math.min(100, count / Math.max(1, ...Object.values(metrics.daily_donations)) * 100)}%` }} /></div><b>{count}</b>
                        </div>
                      ))}
                      {Object.keys(metrics.daily_donations).length === 0 && <div className="chart-empty">No donation records in this range.</div>}
                    </div>
                  </section>
                  <section className="admin-insight-panel">
                    <div className="admin-insight-heading"><div><h3>Current status mix</h3><p>State of records in the selected range</p></div></div>
                    <div className="compact-chart">
                      {Object.entries(statusDistribution(metrics)).map(([status, count]) => (
                        <div className="chart-row" key={status}>
                          <span>{status.replace("_", " ")}</span><div className="chart-track"><span className={`chart-fill chart-fill-${status}`} style={{ width: `${Math.min(100, count / Math.max(1, ...Object.values(statusDistribution(metrics))) * 100)}%` }} /></div><b>{count}</b>
                        </div>
                      ))}
                      {Object.keys(metrics.daily_status_counts).length === 0 && <div className="chart-empty">No donation statuses in this range.</div>}
                    </div>
                  </section>
                  <section className="admin-insight-panel admin-operations-panel">
                    <div className="admin-insight-heading"><div><h3>Recent activity</h3><p>Latest recorded lifecycle and account events</p></div><button className="text-button" onClick={() => navigateTo("activity")}>View activity</button></div>
                    {!localDemoEnabled ? (
                      <div className="chart-empty">Global activity history is not available in the cloud adapter.</div>
                    ) : adminActivity.length === 0 ? (
                      <div className="chart-empty">No recent events are recorded.</div>
                    ) : adminActivity.slice(0, 4).map((event) => (
                      <div className="admin-activity-row" key={event.id}>
                        <span className="event-marker"><Activity size={14} /></span>
                        <span><strong>{describeEvent(event.event_type)}</strong><small>{displayIdentityName(event.actor_id)} · {new Date(event.occurred_at).toLocaleString()}</small></span>
                        <span className="event-transition">{event.after_status ?? "—"}</span>
                      </div>
                    ))}
                  </section>
                  <section className="admin-insight-panel">
                    <div className="admin-insight-heading"><div><h3>Latest ETL run</h3><p>Local Pandas data-quality pipeline</p></div><button className="text-button" onClick={() => navigateTo("etl")}>ETL center</button></div>
                    {!localDemoEnabled ? (
                      <div className="chart-empty">ETL job status is not configured for this cloud adapter.</div>
                    ) : etlRuns.length === 0 ? (
                      <div className="chart-empty">No ETL run has been recorded in this API process.</div>
                    ) : (
                      <div className="latest-run">
                        <div><strong>{new Date(etlRuns[0].started_at).toLocaleString()}</strong><span className={`status status-${etlRuns[0].status === "succeeded" ? "available" : etlRuns[0].status === "failed" ? "expired" : "claimed"}`}>{etlRuns[0].status}</span></div>
                        <small>{etlRuns[0].input_records} input · {etlRuns[0].total_clean_donations} accepted · {etlRuns[0].rejected_records} rejected · {etlRuns[0].duplicate_records} duplicates</small>
                        {etlRuns[0].error && <small className="run-error-summary">{etlRuns[0].error}</small>}
                      </div>
                    )}
                  </section>
                  <section className="admin-insight-panel admin-attention-panel">
                    <div className="admin-insight-heading"><div><h3>Pickup deadline watch</h3><p>Open listings with a deadline in the next 24 hours or already passed</p></div><button className="text-button" onClick={() => navigateTo("donations")}>Review records</button></div>
                    {(() => {
                      const now = Date.now();
                      const watchList = donations
                        .filter((donation) => ["available", "claimed"].includes(donation.status))
                        .filter((donation) => new Date(donation.pickup_deadline).getTime() <= now + 24 * 60 * 60 * 1000)
                        .sort((left, right) => left.pickup_deadline.localeCompare(right.pickup_deadline))
                        .slice(0, 4);
                      return watchList.length === 0 ? (
                        <div className="chart-empty">No open records are due within the next 24 hours.</div>
                      ) : watchList.map((donation) => {
                        const overdue = new Date(donation.pickup_deadline).getTime() <= now;
                        return (
                          <button className="deadline-watch-row" key={donation.id} onClick={() => openDonationDetails(donation)}>
                            <span className={`deadline-watch-icon ${overdue ? "deadline-watch-overdue" : ""}`}>{overdue ? <CircleX size={15} /> : <Clock3 size={15} />}</span>
                            <span><strong>{donation.food_name}</strong><small>{donation.status === "claimed" ? "Claimed · " : "Available · "}{formatDeadline(donation.pickup_deadline)}</small></span>
                            <span className={`deadline-watch-label ${overdue ? "deadline-watch-label-overdue" : ""}`}>{overdue ? "Overdue" : "Due soon"}</span>
                          </button>
                        );
                      });
                    })()}
                  </section>
                </div>
                {!localDemoEnabled && <div className="info-callout"><ShieldCheck size={17} />Cloud account and operational data are limited to what this adapter reports; ETL and global activity are not configured here.</div>}
              </>
            ) : <div className="empty-state"><LoaderCircle className="spin" />Loading verified operations data…</div>}
          </section>
        )}

        {identity && activePage === "overview" && identity.role !== "admin" && dashboard && (
          <section className="portal-overview-grid">
            <div className="overview-section">
              <div className="overview-section-heading"><div><span className="eyebrow">YOUR WORKSPACE</span><h3>{identity.role === "donor" ? "Recent claim activity" : "Upcoming collections"}</h3></div><span className="live-source">Live application data</span></div>
              {identity.role === "ngo" ? (
                dashboard.upcoming_pickups.length === 0
                  ? <div className="overview-empty">No upcoming collections. Browse available food to find a match.</div>
                  : dashboard.upcoming_pickups.map((item) => (
                    <button className="overview-activity-row" type="button" key={item.id} onClick={() => { setSelectedDonationId(item.id); setActivePage("detail"); void showTimeline(item.id); }}>
                      <span className="overview-food-mark"><ShoppingBasket size={15} /></span>
                      <span><strong>{item.food_name}</strong><small>{item.quantity} {item.unit} · {formatDeadline(item.pickup_deadline)}</small></span>
                      <span className={`status status-${item.status}`}>{item.status.replace("_", " ")}</span>
                    </button>
                  ))
              ) : (
                dashboard.recent_donations.filter((item) => item.claimed_by).length === 0
                  ? <div className="overview-empty">No claims on your donations yet. New claims will appear here.</div>
                  : dashboard.recent_donations.filter((item) => item.claimed_by).slice(0, 5).map((item) => (
                    <button className="overview-activity-row" type="button" key={item.id} onClick={() => { setSelectedDonationId(item.id); setActivePage("detail"); void showTimeline(item.id); }}>
                      <span className="overview-food-mark"><HeartHandshake size={15} /></span>
                      <span><strong>{item.food_name}</strong><small>{displayIdentityName(item.claimed_by)} · {formatDeadline(item.pickup_deadline)}</small></span>
                      <span className={`status status-${item.status}`}>{item.status.replace("_", " ")}</span>
                    </button>
                  ))
              )}
            </div>
            <div className="overview-section overview-quantity-section">
              <div className="overview-section-heading"><div><span className="eyebrow">REDISTRIBUTION</span><h3>Completed quantities</h3></div><span className="quantity-caption">By unit</span></div>
              {Object.entries(dashboard.completed_quantity_by_unit).length === 0
                ? <div className="overview-empty">Completed quantities will appear after a pickup is confirmed.</div>
                : Object.entries(dashboard.completed_quantity_by_unit).map(([unitName, quantity]) => (
                  <div className="quantity-row" key={unitName}><span>{unitName}</span><strong>{quantity}</strong></div>
                ))}
            </div>
          </section>
        )}

        {identity && (showDonationList || showSidePanel) && <div className={`exchange-layout ${showSidePanel && !showDonationList ? "layout-panel-only" : ""} ${showDonationList && !showSidePanel ? "layout-list-only" : ""}`}>
          {showDonationList && <div className="listing-column">
            <div className="list-toolbar">
              <h3>{activePage === "browse" ? "Available food" : activePage === "claims" || activePage === "activity" ? "Active claims" : activePage === "history" ? "Closed records" : identity.role === "donor" ? "Your donation records" : identity.role === "ngo" ? "Your food marketplace" : "Platform donations"} <span className="count-pill">{visibleDonations.length} loaded</span></h3>
              <label className="sort-label">Sort
                <select value={sortOrder} onChange={(event) => setSortOrder(event.target.value as "newest" | "deadline")}>
                  <option value="newest">Newest first</option>
                  <option value="deadline">Pickup deadline</option>
                </select>
              </label>
            </div>
            <div className="filter-toolbar">
              <label>
                <span className="sr-only">Search donations</span>
                <input value={donationSearch} onChange={(event) => setDonationSearch(event.target.value)} placeholder="Search food or location" />
              </label>
              <label>
                <span className="sr-only">Filter by status</span>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="">All statuses</option>
                  {["available", "claimed", "picked_up", "cancelled", "expired"].map((status) => (
                    <option key={status} value={status}>{status.replace("_", " ")}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="sr-only">Filter by food category</span>
                <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                  <option value="">All categories</option>
                  {["produce", "bakery", "prepared meals", "dairy", "packaged", "other"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label>
                <span className="sr-only">Filter location</span>
                <input value={locationFilter} onChange={(event) => setLocationFilter(event.target.value)} placeholder="Location" maxLength={160} />
              </label>
              <label>
                <span className="sr-only">Pickup by date</span>
                <input type="date" value={deadlineFilter} onChange={(event) => setDeadlineFilter(event.target.value)} aria-label="Pickup by date" />
              </label>
            </div>
            {loading ? (
              <div className="empty-state"><LoaderCircle className="spin" size={24} /><span>Loading the exchange…</span></div>
            ) : visibleDonations.length === 0 ? (
              <div className="empty-state"><Utensils size={25} /><strong>No matching donations.</strong><span>Try changing a filter, or check back later.</span></div>
            ) : (
              identity.role === "admin" ? (
                <div className="admin-table-scroll" role="region" aria-label="Donation records" tabIndex={0}>
                  <table className="admin-donations-table">
                    <caption className="sr-only">Donation records and their current status</caption>
                    <thead>
                      <tr><th scope="col">Donation</th><th scope="col">Quantity</th><th scope="col">Donor</th><th scope="col">Recipient</th><th scope="col">Pickup deadline</th><th scope="col">Status</th><th scope="col">Details</th></tr>
                    </thead>
                    <tbody>
                      {visibleDonations.map((donation) => (
                        <tr key={donation.id}>
                          <th scope="row"><strong>{donation.food_name}</strong><small>{donation.category}{donation.pickup_location ? ` · ${donation.pickup_location}` : ""}</small></th>
                          <td>{donation.quantity} {donation.unit}</td>
                          <td>{displayIdentityName(donation.donor_id)}</td>
                          <td>{displayIdentityName(donation.claimed_by)}</td>
                          <td>{formatDeadline(donation.pickup_deadline)}</td>
                          <td><span className={`status status-${donation.status}`}>{donation.status.replace("_", " ")}</span></td>
                          <td><button className="text-button" disabled={busy} onClick={() => openDonationDetails(donation)}>View</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="donation-list">
                {visibleDonations.map((donation) => (
                  <article className={`donation-card ${donation.status !== "available" ? "card-muted" : ""} ${editingDonation?.id === donation.id ? "card-editing" : ""}`} key={donation.id}>
                    <div className="food-icon"><Boxes size={22} /></div>
                    <div className="donation-content">
                      <div className="card-title-row">
                        <h4>{donation.food_name}</h4>
                        <span className={`status status-${donation.status}`}>{donation.status.replace("_", " ")}</span>
                      </div>
                      <p className="donation-quantity">{donation.quantity} {donation.unit}</p>
                      {donation.description && <p className="donation-description">{donation.description}</p>}
                      {(donation.category !== "other" || donation.pickup_location) && (
                        <div className="card-meta">{donation.category}{donation.pickup_location ? ` · ${donation.pickup_location}` : ""}</div>
                      )}
                      <div className="card-meta"><CalendarClock size={14} /><span>Pickup by {formatDeadline(donation.pickup_deadline)}</span></div>
                      {donation.claimed_by && <div className="claimed-note">Claimed by {displayIdentityName(donation.claimed_by)}</div>}
                    </div>
                    <div className="card-actions">
                      {identity.role === "donor" &&
                        donation.donor_id === identity.id &&
                        donation.status === "available" &&
                        editingDonation?.id !== donation.id && (
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() => setEditingDonation({
                              ...donation,
                              pickup_deadline: localDateTimeValueFrom(donation.pickup_deadline),
                            })}
                          >
                            Edit
                          </button>
                        )}
                      {editingDonation?.id === donation.id && (
                        <form className="edit-donation-form" onSubmit={(event) => void saveDonationEdit(event)}>
                          <label className="field-label" htmlFor={`edit-food-${donation.id}`}>Food name</label>
                          <input
                            id={`edit-food-${donation.id}`}
                            value={editingDonation.food_name}
                            minLength={2}
                            maxLength={100}
                            required
                            onChange={(event) => setEditingDonation({ ...editingDonation, food_name: event.target.value })}
                          />
                          <label className="field-label" htmlFor={`edit-description-${donation.id}`}>Description</label>
                          <textarea
                            id={`edit-description-${donation.id}`}
                            value={editingDonation.description}
                            maxLength={500}
                            rows={2}
                            onChange={(event) => setEditingDonation({ ...editingDonation, description: event.target.value })}
                          />
                          <label className="field-label" htmlFor={`edit-category-${donation.id}`}>Category</label>
                          <select
                            id={`edit-category-${donation.id}`}
                            value={editingDonation.category}
                            onChange={(event) => setEditingDonation({ ...editingDonation, category: event.target.value })}
                          >
                            {["other", "produce", "bakery", "prepared meals", "dairy", "packaged"].map((item) => <option key={item} value={item}>{item}</option>)}
                          </select>
                          <div className="form-row">
                            <div className="field-group">
                              <label className="field-label" htmlFor={`edit-quantity-${donation.id}`}>Quantity</label>
                              <input
                                id={`edit-quantity-${donation.id}`}
                                type="number"
                                min="0.1"
                                max="100000"
                                step="0.1"
                                value={editingDonation.quantity}
                                required
                                onChange={(event) => setEditingDonation({ ...editingDonation, quantity: Number(event.target.value) })}
                              />
                            </div>
                            <div className="field-group">
                              <label className="field-label" htmlFor={`edit-unit-${donation.id}`}>Unit</label>
                              <input
                                id={`edit-unit-${donation.id}`}
                                value={editingDonation.unit}
                                maxLength={30}
                                required
                                onChange={(event) => setEditingDonation({ ...editingDonation, unit: event.target.value })}
                              />
                            </div>
                          </div>
                          <label className="field-label" htmlFor={`edit-deadline-${donation.id}`}>Pickup by</label>
                          <input
                            id={`edit-deadline-${donation.id}`}
                            type="datetime-local"
                            value={editingDonation.pickup_deadline}
                            min={localDateTimeValue(0)}
                            required
                            onChange={(event) => setEditingDonation({ ...editingDonation, pickup_deadline: event.target.value })}
                          />
                          <label className="field-label" htmlFor={`edit-location-${donation.id}`}>Pickup location</label>
                          <input
                            id={`edit-location-${donation.id}`}
                            value={editingDonation.pickup_location}
                            maxLength={160}
                            onChange={(event) => setEditingDonation({ ...editingDonation, pickup_location: event.target.value })}
                          />
                          <button className="button button-primary" disabled={busy}>Save changes</button>
                          <button className="text-button" type="button" onClick={() => setEditingDonation(null)}>Cancel edit</button>
                        </form>
                      )}
                      <button className="text-button" disabled={busy} onClick={() => {
                        openDonationDetails(donation);
                      }}>Details</button>
                      {identity.role === "ngo" && donation.status === "available" && !canClaim(donation) && (
                        <span className="deadline-expired">Pickup deadline passed</span>
                      )}
                      {canClaim(donation) && <button className="button button-primary" disabled={busy} onClick={() => setConfirmation({
                        title: "Claim this donation?",
                        message: `Reserve ${donation.food_name} for your organization? The donation will no longer be available to other recipients.`,
                        confirmLabel: "Confirm claim",
                        onConfirm: () => void perform(
                          () => api.claimDonation(donation.id, identity.id),
                          "Donation claimed. Coordinate pickup with the donor.",
                        ),
                      })}>Claim</button>}
                      {canConfirmPickup(donation) && <button className="button button-primary" disabled={busy} onClick={() => setConfirmation({
                        title: "Confirm collection?",
                        message: `Confirm that your organization collected ${donation.food_name}?`,
                        confirmLabel: "Confirm pickup",
                        onConfirm: () => void perform(
                          () => api.updateStatus(donation.id, identity.id, "picked_up"),
                          "Pickup confirmed. Thank you for making it count.",
                        ),
                      })}><Check size={15} /> Picked up</button>}
                      {canCancel(donation) && <button className="text-button" disabled={busy} onClick={() => setConfirmation({
                        title: "Cancel this donation?",
                        message: `${donation.food_name} will no longer be available to recipients.`,
                        confirmLabel: "Cancel donation",
                        onConfirm: () => void perform(
                          () => api.updateStatus(donation.id, identity.id, "cancelled"),
                          "Donation removed from the exchange.",
                        ),
                      })}>Cancel</button>}
                    </div>
                  </article>
                ))}
                {Object.keys(donationCursors).length > 0 && (
                  <button className="button button-quiet" disabled={busy || loading} onClick={() => void loadMoreDonations()}>
                    Load more donations
                  </button>
                )}
              </div>
            )}
          </div>}

          {showSidePanel && <aside className="sidebar">
            {identity.role === "donor" ? (
              <form className="form-card" onSubmit={(event) => void createDonation(event)}>
                <div className="form-card-icon"><Plus size={19} /></div>
                <div className="eyebrow">PASS IT ON</div>
                <h3>Share a donation</h3>
                <p>Have good food to spare? Add it to the exchange.</p>
                <label className="field-label" htmlFor="food-name">What are you sharing?</label>
                <input id="food-name" value={foodName} onChange={(event) => setFoodName(event.target.value)} placeholder="e.g. Fresh vegetable boxes" minLength={2} maxLength={100} required />
                <label className="field-label" htmlFor="food-description">Description (optional)</label>
                <textarea id="food-description" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={500} rows={2} />
                <label className="field-label" htmlFor="food-category">Category</label>
                <select id="food-category" value={category} onChange={(event) => setCategory(event.target.value)}>
                  {["other", "produce", "bakery", "prepared meals", "dairy", "packaged"].map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
                <div className="form-row">
                  <div className="field-group">
                    <label className="field-label" htmlFor="quantity">Quantity</label>
                    <input id="quantity" type="number" min="0.1" max="100000" step="0.1" value={quantity} onChange={(event) => setQuantity(event.target.value)} required />
                  </div>
                  <div className="field-group">
                    <label className="field-label" htmlFor="unit">Unit</label>
                    <input id="unit" value={unit} onChange={(event) => setUnit(event.target.value)} maxLength={30} required />
                  </div>
                </div>
                <label className="field-label" htmlFor="deadline">Pickup by</label>
                <input id="deadline" type="datetime-local" value={deadline} min={localDateTimeValue(0)} onChange={(event) => setDeadline(event.target.value)} required />
                <label className="field-label" htmlFor="pickup-location">Pickup location (optional)</label>
                <input id="pickup-location" value={pickupLocation} onChange={(event) => setPickupLocation(event.target.value)} maxLength={160} />
                <button className="button button-primary button-wide" type="submit" disabled={busy}>
                  {busy ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />} Share donation
                </button>
                <div className="privacy-note"><ShieldCheck size={14} /> Demo only. Please don't enter personal information.</div>
              </form>
            ) : (
              <div className="role-card">
                <div className="role-icon">{identity.role === "admin" ? <ShieldCheck size={20} /> : <HeartHandshake size={20} />}</div>
                <div className="eyebrow">{identity.role === "admin" ? "ADMIN VIEW" : "COMMUNITY PARTNER"}</div>
                <h3>{identity.role === "admin" ? "A clearer picture." : "Make a difference today."}</h3>
                <p>{identity.role === "admin" ? (localDemoEnabled ? "See live demo metrics from the local application data." : "Review bounded live application metrics; user administration is not enabled in the cloud adapter.") : "Claim available donations to reserve them for your community kitchen."}</p>
                {identity.role === "admin" && metrics && (
                  <div className="analytics-mini">
                    <div><span>All donations</span><strong>{metrics.total_donations}</strong></div>
                    <div><span>Claimed</span><strong>{metrics.claimed_donations}</strong></div>
                    <div><span>Completed</span><strong>{metrics.completed_pickups}</strong></div>
                    <div><span>Available</span><strong>{metrics.available_donations}</strong></div>
                    <div><span>Cancelled / expired</span><strong>{metrics.cancelled_donations} / {metrics.expired_donations}</strong></div>
                    <div><span>Claim / completion</span><strong>{(metrics.claim_success_rate * 100).toFixed(0)}% / {(metrics.completion_rate * 100).toFixed(0)}%</strong></div>
                    <div><span>Expiry rate</span><strong>{(metrics.expiry_rate * 100).toFixed(0)}%</strong></div>
                    <div><span>Avg. time to claim</span><strong>{metrics.average_time_to_claim_seconds === null ? "—" : `${Math.round(metrics.average_time_to_claim_seconds / 60)} min`}</strong></div>
                    <div><span>Completed quantities</span><strong>{Object.entries(metrics.completed_quantity_by_unit).map(([unitName, amount]) => `${amount} ${unitName}`).join(", ") || "0"}</strong></div>
                  </div>
                )}
                {identity.role === "admin" && metrics && (
                  <>
                    <label className="field-label" htmlFor="analytics-start">Analytics start date (UTC)</label>
                    <input id="analytics-start" type="date" value={analyticsStart} onChange={(event) => setAnalyticsStart(event.target.value)} />
                    <label className="field-label" htmlFor="analytics-end">Analytics end date (UTC)</label>
                    <input id="analytics-end" type="date" value={analyticsEnd} onChange={(event) => setAnalyticsEnd(event.target.value)} />
                    <label className="field-label" htmlFor="analytics-category">Analytics category</label>
                    <select id="analytics-category" value={analyticsCategory} onChange={(event) => setAnalyticsCategory(event.target.value)}>
                      <option value="">All categories</option>
                      {["other", "produce", "bakery", "prepared meals", "dairy", "packaged"].map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                    <label className="field-label" htmlFor="analytics-location">Analytics location contains</label>
                    <input id="analytics-location" value={analyticsLocation} onChange={(event) => setAnalyticsLocation(event.target.value)} maxLength={160} />
                    {localDemoEnabled && (
                      <>
                        <button className="button button-quiet" disabled={busy} onClick={() => void perform(async () => {
                          const result = await api.expireDonations(identity.id);
                          return result;
                        }, "Expiry processing completed.")}>Process expired listings</button>
                      </>
                    )}
                    <div className="chart-card">
                      <strong>Daily donation records</strong>
                      <small>UTC dates; {localDemoEnabled ? "local database" : "cloud query limited to 500 records"}.</small>
                      {Object.entries(metrics.daily_donations).slice(-7).map(([day, count]) => (
                        <div className="chart-row" key={day}>
                          <span>{day}</span><div className="chart-track"><span style={{ width: `${Math.min(100, count / Math.max(1, ...Object.values(metrics.daily_donations)) * 100)}%` }} /></div><b>{count}</b>
                        </div>
                      ))}
                    </div>
                    <small>Analytics updated {new Date(metrics.last_updated).toLocaleString()} · {metrics.data_source === "local_live" ? "local live database" : "cloud data, bounded to 500 donations"}.</small>
                  </>
                )}
                {identity.role === "ngo" && <div className="role-hint"><ArrowUpRight size={15} /> Choose an available listing to reserve it.</div>}
              </div>
            )}

            {(activePage === "overview" || activePage === "browse") && <div className="how-card" id="how-it-works">
              <div className="eyebrow">THREE LITTLE STEPS</div>
              <h3>From extra to essential.</h3>
              <div className="step"><span>01</span><div><strong>Share what you can</strong><small>List surplus food and a pickup time.</small></div></div>
              <div className="step"><span>02</span><div><strong>A local NGO claims it</strong><small>One claim reserves each donation.</small></div></div>
              <div className="step"><span>03</span><div><strong>Food finds a new home</strong><small>Confirm pickup and celebrate the good.</small></div></div>
            </div>}
          </aside>}
        </div>}
        {identity?.role === "admin" && activePage === "users" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><Users size={18} /></span><div><h3>Local demo identities</h3><p>Role, status, and account controls from the local application database.</p></div></div>
            {!localDemoEnabled ? (
              <div className="info-callout"><ShieldCheck size={17} />User administration is not implemented for the cloud adapter. These controls are intentionally local-demo only.</div>
            ) : (
              <>
                <div className="workspace-filters">
                  <label><span className="field-label">Search by account name</span><input value={userSearch} onChange={(event) => setUserSearch(event.target.value)} placeholder="Find a profile" /></label>
                  <label><span className="field-label">Role</span><select value={userRoleFilter} onChange={(event) => setUserRoleFilter(event.target.value)}><option value="">All roles</option><option value="donor">Donor</option><option value="ngo">Recipient</option><option value="admin">Administrator</option></select></label>
                  <label><span className="field-label">Account status</span><select value={userStatusFilter} onChange={(event) => setUserStatusFilter(event.target.value)}><option value="">All statuses</option><option value="active">Active</option><option value="suspended">Suspended</option></select></label>
                </div>
                <div className="user-table">
                  <div className="user-table-heading"><span>User identity</span><span>Role</span><span>Account</span><span>Created</span><span>Actions</span></div>
                  {visibleUsers.map((user) => (
                    <article className="user-table-row" key={user.user_id}>
                      <strong>{displayIdentityName(user.user_id)}</strong>
                      <span className="role-tag">{user.role}</span>
                      <span className={`account-state state-${user.status}`}>{user.status}</span>
                      <span>{new Date(user.created_at).toLocaleDateString()}</span>
                      <span className="user-row-actions">
                        <button className="text-button" onClick={() => void loadUserActivity(user.user_id)}>Activity</button>
                        {user.user_id !== identity.id && <button className="text-button" disabled={busy} onClick={() => confirmUserStatusChange(user)}>{user.status === "active" ? "Suspend" : "Reactivate"}</button>}
                      </span>
                    </article>
                  ))}
                  {visibleUsers.length === 0 && <div className="empty-state"><Users size={22} />No demo user records match these filters.</div>}
                </div>
                {userCursor && <button className="button button-quiet" disabled={busy} onClick={() => void loadMoreUsers()}>Load more users</button>}
                {selectedUserId && <div className="timeline-panel">
                  <div className="list-toolbar"><h3>Activity for {displayIdentityName(selectedUserId)}</h3><button className="text-button" onClick={() => { setSelectedUserId(null); setUserActivity([]); }}>Close</button></div>
                  {userActivity.length === 0 ? <div className="empty-state">No recorded user activity.</div> : userActivity.map((event) => (
                    <article className="timeline-event" key={event.id}><strong>{event.event_type.replace(/_/g, " ")}</strong><span>{event.entity_type === "user" ? "Account record" : "Donation record"}</span><small>{new Date(event.occurred_at).toLocaleString()} · {displayIdentityName(event.actor_id)}</small></article>
                  ))}
                </div>}
              </>
            )}
          </section>
        )}
        {identity?.role === "admin" && activePage === "analytics" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><Activity size={18} /></span><div><h3>Application analytics</h3><p>{metrics?.data_source === "local_live" ? "Live metrics from the local application database." : "Cloud analytics are bounded to the records supported by the cloud adapter."}</p></div></div>
            <div className="workspace-filters analytics-filters">
              <label><span className="field-label">Created from (UTC)</span><input type="date" value={analyticsStart} onChange={(event) => setAnalyticsStart(event.target.value)} /></label>
              <label><span className="field-label">Created through (UTC)</span><input type="date" value={analyticsEnd} onChange={(event) => setAnalyticsEnd(event.target.value)} /></label>
              <label><span className="field-label">Current status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">All statuses</option>{["available", "claimed", "picked_up", "cancelled", "expired"].map((status) => <option key={status} value={status}>{status.replace("_", " ")}</option>)}</select></label>
              <label><span className="field-label">Food category</span><select value={analyticsCategory} onChange={(event) => setAnalyticsCategory(event.target.value)}><option value="">All categories</option>{["other", "produce", "bakery", "prepared meals", "dairy", "packaged"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label><span className="field-label">Location contains</span><input value={analyticsLocation} onChange={(event) => setAnalyticsLocation(event.target.value)} maxLength={160} /></label>
              <button className="text-button" disabled={!analyticsStart && !analyticsEnd && !statusFilter && !analyticsCategory && !analyticsLocation} onClick={() => {
                setAnalyticsStart("");
                setAnalyticsEnd("");
                setStatusFilter("");
                setAnalyticsCategory("");
                setAnalyticsLocation("");
              }}>Clear filters</button>
            </div>
            {metrics ? (
              <>
                <div className="metric-grid">
                  {[
                    ["All donations", metrics.total_donations],
                    ["Available", metrics.available_donations],
                    ["Claimed", metrics.claimed_donations],
                    ["Completed pickups", metrics.completed_pickups],
                    ["Cancelled", metrics.cancelled_donations],
                    ["Expired", metrics.expired_donations],
                    ["Registered donors", metrics.donors_registered ?? "Unavailable"],
                    ["Registered recipients", metrics.recipients_registered ?? "Unavailable"],
                    ["Claim rate", `${(metrics.claim_success_rate * 100).toFixed(1)}%`],
                    ["Completion rate", `${(metrics.completion_rate * 100).toFixed(1)}%`],
                    ["Expiry rate", `${(metrics.expiry_rate * 100).toFixed(1)}%`],
                    ["Average time to claim", metrics.average_time_to_claim_seconds === null ? "Unavailable" : `${Math.round(metrics.average_time_to_claim_seconds / 60)} min`],
                  ].map(([label, amount]) => <div className="metric-card" key={label}><span>{label}</span><strong>{amount}</strong></div>)}
                </div>
                <div className="analytics-detail-grid">
                  <div className="chart-card">
                    <strong>Daily donation records</strong><small>UTC dates · based on the current analytics filters.</small>
                    {Object.entries(metrics.daily_donations).slice(-14).map(([day, count]) => (
                      <div className="chart-row" key={day}><span>{day}</span><div className="chart-track"><span style={{ width: `${Math.min(100, count / Math.max(1, ...Object.values(metrics.daily_donations)) * 100)}%` }} /></div><b>{count}</b></div>
                    ))}
                    {Object.keys(metrics.daily_donations).length === 0 && <p className="muted-copy">No daily records in this range.</p>}
                  </div>
                  <div className="chart-card">
                    <strong>Completed pickups over time</strong><small>Counted by donation creation date within current filters.</small>
                    {Object.entries(metrics.daily_completed_pickups).slice(-14).map(([day, count]) => (
                      <div className="chart-row" key={day}><span>{day}</span><div className="chart-track"><span style={{ width: `${Math.min(100, count / Math.max(1, ...Object.values(metrics.daily_completed_pickups)) * 100)}%` }} /></div><b>{count}</b></div>
                    ))}
                    {Object.keys(metrics.daily_completed_pickups).length === 0 && <p className="muted-copy">No completed pickups in this range.</p>}
                  </div>
                  <div className="chart-card">
                    <strong>Donation status distribution</strong><small>Current status of records in the filtered population.</small>
                    {Object.entries(statusDistribution(metrics)).map(([status, count]) => (
                      <div className="chart-row" key={status}><span>{status.replace("_", " ")}</span><div className="chart-track"><span style={{ width: `${Math.min(100, count / Math.max(1, ...Object.values(statusDistribution(metrics))) * 100)}%` }} /></div><b>{count}</b></div>
                    ))}
                    {Object.keys(metrics.daily_status_counts).length === 0 && <p className="muted-copy">No donation statuses in this range.</p>}
                  </div>
                  <div className="chart-card">
                    <strong>Food categories</strong><small>Donation records grouped by category.</small>
                    {Object.entries(metrics.category_counts).map(([categoryName, count]) => (
                      <div className="chart-row" key={categoryName}><span>{categoryName}</span><div className="chart-track"><span style={{ width: `${Math.min(100, count / Math.max(1, ...Object.values(metrics.category_counts)) * 100)}%` }} /></div><b>{count}</b></div>
                    ))}
                    {Object.keys(metrics.category_counts).length === 0 && <p className="muted-copy">No category data in this range.</p>}
                  </div>
                  <div className="chart-card">
                    <strong>Completed quantities by unit</strong><small>Units are kept separate; quantities are not combined across different measures.</small>
                    {Object.entries(metrics.completed_quantity_by_unit).map(([unitName, amount]) => <div className="quantity-row" key={unitName}><span>{unitName}</span><strong>{amount}</strong></div>)}
                    {Object.keys(metrics.completed_quantity_by_unit).length === 0 && <p className="muted-copy">No completed pickup quantities yet.</p>}
                  </div>
                </div>
                <small className="data-footnote">Last updated {new Date(metrics.last_updated).toLocaleString()} · {metrics.data_source === "local_live" ? "local live database" : "cloud query, bounded by the adapter"}.</small>
              </>
            ) : <div className="empty-state"><LoaderCircle className="spin" />Loading verified analytics…</div>}
          </section>
        )}
        {identity?.role === "admin" && activePage === "etl" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><Database size={18} /></span><div><h3>Local Pandas ETL</h3><p>Extracts current local donations, validates and normalizes records, then writes clean, rejected, duplicate, and summary report files.</p></div></div>
            {!localDemoEnabled ? (
              <div className="info-callout"><ShieldCheck size={17} />A live ETL run is unavailable in this cloud adapter. AWS Glue is documented as a future deployment option; no cloud job is being simulated.</div>
            ) : (
              <>
                <div className="etl-callout"><strong>Local-only execution · synchronous</strong><span><b>Source:</b> a bounded export of current SQLite donations. <b>Transform:</b> Pandas validation, normalization, and duplicate detection. <b>Destination:</b> report files in the configured temporary output directory; this action does not upload to S3.</span></div>
                <button className="button button-primary" disabled={busy} onClick={() => setConfirmation({
                  title: "Run the local ETL pipeline?",
                  message: "This will read the current local donation export and write report files to the configured temporary output directory. It does not modify donation records or upload to AWS.",
                  confirmLabel: "Run ETL pipeline",
                  onConfirm: () => void runETL(),
                })}>{busy ? <LoaderCircle size={15} className="spin" /> : <RotateCw size={15} />} Run ETL pipeline</button>
              </>
            )}
            <div className="run-list">
              <div className="run-list-heading"><strong>Recent runs</strong><span>{etlRuns.length} available in this API process</span></div>
              {etlRuns.map((run) => (
                <article className="run-card" key={run.run_id}>
                  <div className="run-card-top"><strong>{new Date(run.started_at).toLocaleString()}</strong><span className={`status status-${run.status === "succeeded" ? "available" : run.status === "failed" ? "expired" : "claimed"}`}>{run.status}</span></div>
                  <span>{run.mode} run · {run.completed_at ? `completed ${new Date(run.completed_at).toLocaleString()}` : "in progress"} · {run.processing_duration_seconds === null ? "duration pending" : `${run.processing_duration_seconds.toFixed(2)} sec`}</span>
                  <div className="run-metrics"><span>{run.input_records} input</span><span>{run.total_clean_donations} clean</span><span>{run.rejected_records} rejected</span><span>{run.duplicate_records} duplicates</span><span>{run.completed_pickups} pickups</span></div>
                  {run.rejected_records > 0 && <small>Rejected row details are available in the rejected-record report.</small>}
                  {run.error && <div className="feedback feedback-error" role="alert">{run.error}</div>}
                </article>
              ))}
              {etlRuns.length === 0 && <div className="empty-state"><Database size={22} /><strong>No ETL runs yet.</strong><span>Start a local run to create analytics outputs.</span></div>}
            </div>
          </section>
        )}
        {identity?.role === "admin" && activePage === "reports" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><Download size={18} /></span><div><h3>Downloadable reports</h3><p>Files are produced by completed ETL runs. Application exports contain synthetic demonstration records.</p></div></div>
            <div className="export-card">
              <div><strong>Application donation export</strong><small>JSON snapshot from the current application adapter.</small></div>
              <button className="button button-quiet" onClick={() => void downloadApplicationExport()}><Download size={15} /> Download JSON</button>
            </div>
            {!localDemoEnabled && <div className="info-callout"><Database size={17} />ETL report downloads are available only for local SQLite runs; no cloud ETL report is represented here.</div>}
            {etlRuns.map((run) => (
              <div className="report-run" key={run.run_id}>
                <div className="report-run-heading"><strong>ETL run · {new Date(run.started_at).toLocaleString()}</strong><span>{run.status}</span></div>
                {run.reports.length === 0 ? <p className="muted-copy">No report files were registered for this run.</p> : <div className="report-links">{run.reports.map((report) => <button className="report-link" key={report} disabled={!localDemoEnabled} onClick={() => void downloadReport(run.run_id, report)}><Download size={14} />{report}</button>)}</div>}
              </div>
            ))}
            {etlRuns.length === 0 && <div className="empty-state"><Download size={22} /><strong>No reports available.</strong><span>Run the local ETL pipeline to create downloadable outputs.</span></div>}
          </section>
        )}
        {identity?.role === "admin" && activePage === "activity" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><Activity size={18} /></span><div><h3>Recent claims and lifecycle events</h3><p>Events are read from the local application audit table. The claim list above shows current claimed donations.</p></div></div>
            {!localDemoEnabled ? (
              <div className="info-callout"><ShieldCheck size={17} />Global activity history is not available in the cloud database adapter.</div>
            ) : adminActivity.length === 0 ? (
              <div className="empty-state"><Activity size={22} /><strong>No activity recorded.</strong><span>Real donation and account events will appear here as they occur.</span></div>
            ) : (
              <div className="event-list">
                {adminActivity.map((event) => (
                  <article className="audit-event" key={event.id}>
                    <span className="event-marker"><Activity size={15} /></span>
                    <div><strong>{event.event_type.replace(/_/g, " ")}</strong><span>{event.entity_type === "user" ? "Account update" : "Donation lifecycle"}</span><small>{new Date(event.occurred_at).toLocaleString()} · {displayIdentityName(event.actor_id)}</small></div>
                    <span className="event-transition">{event.before_status ?? "—"} → {event.after_status ?? "—"}</span>
                  </article>
                ))}
                {activityCursor && <button className="button button-quiet" disabled={busy} onClick={() => void loadMoreActivity()}>Load older activity</button>}
              </div>
            )}
          </section>
        )}
        {identity?.role === "admin" && activePage === "audit" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><History size={18} /></span><div><h3>Application event history</h3><p>Persisted local application events, ordered by occurrence time. Not a cloud-wide audit log.</p></div></div>
            {!localDemoEnabled ? <div className="info-callout"><ShieldCheck size={17} />Global audit history is not available in the cloud database adapter.</div> : (
              <>
                <div className="workspace-filters audit-filters">
                  <label><span className="field-label">Event type</span><select value={activityType} onChange={(event) => setActivityType(event.target.value)}><option value="">All event types</option>{["donation_created", "donation_updated", "donation_claimed", "donation_picked_up", "donation_cancelled", "donation_expired", "user_status_changed"].map((item) => <option key={item} value={item}>{item.replace(/_/g, " ")}</option>)}</select></label>
                  <label><span className="field-label">From date</span><input type="date" value={activityStart} onChange={(event) => setActivityStart(event.target.value)} /></label>
                  <label><span className="field-label">Through date</span><input type="date" value={activityEnd} onChange={(event) => setActivityEnd(event.target.value)} /></label>
                </div>
                <div className="event-list">
                  {adminActivity.map((event) => <article className="audit-event" key={event.id}><span className="event-marker"><Activity size={15} /></span><div><strong>{event.event_type.replace(/_/g, " ")}</strong><span>{event.entity_type === "user" ? "Account record" : "Donation record"}</span><small>{new Date(event.occurred_at).toLocaleString()} · {displayIdentityName(event.actor_id)}</small></div><span className="event-transition">{event.before_status ?? "—"} → {event.after_status ?? "—"}</span></article>)}
                  {adminActivity.length === 0 && <div className="empty-state"><History size={22} /><strong>No events match this selection.</strong><span>Try a different type or date range.</span></div>}
                </div>
                {activityCursor && <button className="button button-quiet" disabled={busy} onClick={() => void loadMoreActivity()}>Load older events</button>}
              </>
            )}
          </section>
        )}
        {identity?.role === "admin" && activePage === "health" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><Activity size={18} /></span><div><h3>Verified system status</h3><p>Values below come from the local health endpoint; unknown means the source is not queried.</p></div></div>
            {health ? (
              <>
                <div className="health-grid">
                  <div className="health-card"><span>API</span><strong className="health-good">{health.api}</strong><small>Checked {new Date(health.checked_at).toLocaleString()}</small></div>
                  <div className="health-card"><span>Database</span><strong className={health.database.status === "healthy" ? "health-good" : "health-bad"}>{health.database.status}</strong><small>{health.database.adapter} · {health.database.donation_count === null ? "count unavailable" : `${health.database.donation_count} donations`}</small></div>
                  <div className="health-card"><span>CI status</span><strong>{health.ci}</strong><small>No CI run is queried by this endpoint.</small></div>
                  <div className="health-card"><span>Deployment</span><strong>{health.deployment}</strong><small>Deployment status is reported, not inferred from local health.</small></div>
                  <div className="health-card"><span>Application mode</span><strong>{health.application_mode}</strong><small>Health check reflects this running API only.</small></div>
                  <div className="health-card"><span>Last ETL</span><strong>{health.etl?.status ?? "No run recorded"}</strong><small>{health.etl ? new Date(health.etl.started_at).toLocaleString() : "ETL history is empty."}</small></div>
                </div>
                {health.database.error_type && <div className="feedback feedback-error">Database check failed: {health.database.error_type}</div>}
              </>
            ) : <div className="empty-state"><LoaderCircle className="spin" />Loading system status…</div>}
          </section>
        )}
        {identity && activePage === "profile" && (
          <section className="workspace-panel">
            <div className="workspace-panel-heading"><span className="workspace-icon"><ShieldCheck size={18} /></span><div><h3>Session identity</h3><p>Account details are intentionally limited to synthetic identity data.</p></div></div>
            <div className="profile-grid">
              <div className="profile-field"><span>Account name</span><strong>{identity.label}</strong></div>
              <div className="profile-field"><span>Application role</span><strong>{identity.role}</strong></div>
              <div className="profile-field"><span>Authentication</span><strong>{localDemoEnabled ? "Local mock identity" : "Cognito OIDC"}</strong></div>
              <div className="profile-field"><span>Data mode</span><strong>{localDemoEnabled ? "Local application database" : "Authenticated application"}</strong></div>
            </div>
            <div className="info-callout"><ShieldCheck size={17} />This project does not request or display personal contact, banking, or identity documents. No editable profile data is stored in this demo.</div>
          </section>
        )}
        {identity && activePage === "detail" && (
          <section className="workspace-panel">
            {selectedDonation ? (
              <>
                <div className="workspace-panel-heading"><span className="workspace-icon"><ShoppingBasket size={18} /></span><div><h3>{selectedDonation.food_name}</h3><p>Donation record and persisted lifecycle history.</p></div></div>
                <div className="detail-grid">
                  <div><span>Status</span><strong className={`status status-${selectedDonation.status}`}>{selectedDonation.status.replace("_", " ")}</strong></div>
                  <div><span>Quantity</span><strong>{selectedDonation.quantity} {selectedDonation.unit}</strong></div>
                  <div><span>Category</span><strong>{selectedDonation.category}</strong></div>
                  <div><span>Pickup deadline</span><strong>{formatDeadline(selectedDonation.pickup_deadline)}</strong></div>
                  <div><span>Donor</span><strong>{displayIdentityName(selectedDonation.donor_id)}</strong></div>
                  <div><span>Recipient</span><strong>{displayIdentityName(selectedDonation.claimed_by)}</strong></div>
                  <div><span>Pickup location</span><strong>{selectedDonation.pickup_location || "Not specified"}</strong></div>
                  <div><span>Description</span><strong>{selectedDonation.description || "No description"}</strong></div>
                </div>
                <div className="detail-actions">
                  {canClaim(selectedDonation) && <button className="button button-primary" disabled={busy} onClick={() => setConfirmation({
                    title: "Claim this donation?",
                    message: `Reserve ${selectedDonation.food_name} for your organization?`,
                    confirmLabel: "Confirm claim",
                    onConfirm: () => {
                      void perform(
                        () => api.claimDonation(selectedDonation.id, identity.id),
                        "Donation claimed. It is now in your active claims.",
                      ).then((succeeded) => {
                        if (succeeded) navigateTo("claims");
                      });
                    },
                  })}>Claim this donation</button>}
                  {canConfirmPickup(selectedDonation) && <button className="button button-primary" disabled={busy} onClick={() => setConfirmation({
                    title: "Confirm collection?",
                    message: `Confirm that your organization collected ${selectedDonation.food_name}?`,
                    confirmLabel: "Confirm pickup",
                    onConfirm: () => {
                      void perform(
                        () => api.updateStatus(selectedDonation.id, identity.id, "picked_up"),
                        "Pickup confirmed. Thank you for making it count.",
                      ).then((succeeded) => {
                        if (succeeded) navigateTo("history");
                      });
                    },
                  })}><Check size={15} /> Confirm collection</button>}
                  {canCancel(selectedDonation) && <button className="button button-quiet" disabled={busy} onClick={() => setConfirmation({
                    title: "Cancel this donation?",
                    message: `${selectedDonation.food_name} will no longer be available to recipients.`,
                    confirmLabel: "Cancel donation",
                    onConfirm: () => {
                      void perform(
                        () => api.updateStatus(selectedDonation.id, identity.id, "cancelled"),
                        "Donation cancelled.",
                      ).then((succeeded) => {
                        if (succeeded) navigateTo("history");
                      });
                    },
                  })}>Cancel donation</button>}
                </div>
                <div className="timeline-panel">
                  <div className="list-toolbar"><h3>Lifecycle events</h3><button className="text-button" onClick={() => void showTimeline(selectedDonation.id)}>Refresh history</button></div>
                  {timeline.length === 0 ? <div className="empty-state"><History size={22} />No events have been recorded for this donation.</div> : timeline.map((event) => <article className="timeline-event" key={event.id}><strong>{event.event_type.replace(/_/g, " ")}</strong><span>{event.before_status ?? "—"} → {event.after_status ?? "—"}</span><small>{new Date(event.occurred_at).toLocaleString()} · {displayIdentityName(event.actor_id)}</small></article>)}
                  {timelineCursor && <button className="button button-quiet" disabled={busy} onClick={() => void loadMoreHistory()}>Load older history</button>}
                </div>
              </>
            ) : <div className="empty-state"><ShoppingBasket size={22} />Select a donation to view its details.</div>}
            <button className="button button-quiet" onClick={() => navigateTo(identity.role === "ngo" ? "browse" : "donations")}>Back to donations</button>
          </section>
        )}
        {timelineId && activePage !== "detail" && (
          <section className="timeline-panel" aria-label="Donation activity timeline">
            <div className="list-toolbar">
              <h3>Donation history</h3>
              <button className="text-button" onClick={() => { setTimelineId(null); setTimeline([]); setTimelineCursor(null); }}>Close</button>
            </div>
            {timeline.length === 0 ? <p className="empty-state">No recorded history is available.</p> : timeline.map((event) => (
              <article className="timeline-event" key={event.id}>
                <strong>{event.event_type.replace(/_/g, " ")}</strong>
                <span>{event.before_status ?? "—"} → {event.after_status ?? "—"}</span>
                <small>{new Date(event.occurred_at).toLocaleString(undefined, { timeZone: "UTC" })} UTC · {displayIdentityName(event.actor_id)}</small>
              </article>
            ))}
            {timelineCursor && <button className="button button-quiet" disabled={busy} onClick={() => void loadMoreHistory()}>Load older history</button>}
          </section>
        )}
      </section>
      </div>
      </div>

      <footer className="footer">
        <a className="brand footer-brand" href="#"><span className="brand-mark"><Leaf size={16} /></span><span>ShareBite<span className="brand-period">.</span></span></a>
        <span>Built for a kinder, less wasteful community.</span>
        <span className="footer-tag">A local cloud computing project</span>
      </footer>
      {confirmation && (
        <div className="dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !busy) setConfirmation(null);
        }}>
          <section
            className="confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby="confirm-message"
          >
            <span className="confirm-dialog-icon"><TriangleAlert size={20} /></span>
            <h2 id="confirm-title">{confirmation.title}</h2>
            <p id="confirm-message">{confirmation.message}</p>
            <div className="dialog-actions">
              <button className="button button-quiet" autoFocus disabled={busy} onClick={() => setConfirmation(null)}>Go back</button>
              <button className="button button-danger" disabled={busy} onClick={() => {
                const action = confirmation.onConfirm;
                setConfirmation(null);
                action();
              }}>{busy ? <LoaderCircle size={15} className="spin" /> : null}{confirmation.confirmLabel}</button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default App;
