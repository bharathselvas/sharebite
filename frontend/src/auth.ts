import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";

const configuredMode = import.meta.env.VITE_AUTH_MODE;
export const localDemoEnabled =
  import.meta.env.DEV && configuredMode === "local-demo";
export const cognitoMode = configuredMode === "cognito";

const issuer = import.meta.env.VITE_COGNITO_ISSUER;
const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID;
export const cognitoConfigured = Boolean(issuer && clientId);

let manager: UserManager | undefined;

function getUserManager(): UserManager {
  if (!issuer || !clientId) {
    throw new Error("Set VITE_COGNITO_ISSUER and VITE_COGNITO_CLIENT_ID to enable Cognito login.");
  }
  if (!manager) {
    manager = new UserManager({
      authority: issuer,
      client_id: clientId,
      redirect_uri: `${window.location.origin}/auth/callback`,
      post_logout_redirect_uri: `${window.location.origin}/`,
      response_type: "code",
      scope: "openid",
      automaticSilentRenew: true,
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    });
  }
  return manager;
}

export async function getSignedInUser(): Promise<User | null> {
  return getUserManager().getUser();
}

export async function readAccessToken(): Promise<string | null> {
  return getAccessToken(await getSignedInUser());
}

export async function completeSignIn(): Promise<User> {
  return getUserManager().signinRedirectCallback();
}

export async function beginSignIn(): Promise<void> {
  await getUserManager().signinRedirect();
}

export async function beginSignOut(): Promise<void> {
  await getUserManager().signoutRedirect();
}

export function getAccessToken(user: User | null): string | null {
  return user && !user.expired ? user.access_token : null;
}

export function userRole(user: User | null): "donor" | "ngo" | "admin" | null {
  if (!user || user.expired) return null;
  const rawGroups = user.profile["cognito:groups"];
  const groups = Array.isArray(rawGroups) ? rawGroups.map(String) : [];
  const roles = [
    groups.includes("food-admins") ? "admin" : null,
    groups.includes("food-ngos") ? "ngo" : null,
    groups.includes("food-donors") ? "donor" : null,
  ].filter((role): role is "donor" | "ngo" | "admin" => role !== null);
  return roles.length === 1 ? roles[0] : null;
}
