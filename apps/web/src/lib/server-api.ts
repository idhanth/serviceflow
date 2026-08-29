import { API_BASE_URL, getActiveOrganizationId, getSessionToken } from "@/lib/session";

/**
 * Server component fetch: talks to the API directly with the session cookie.
 * Returns null on 401/403 so pages can redirect rather than crash.
 */
export async function serverFetchData<T>(path: string): Promise<T | null> {
  const token = await getSessionToken();
  if (!token) return null;

  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const organizationId = await getActiveOrganizationId();
  if (organizationId) headers["X-Organization-Id"] = organizationId;

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/${path.replace(/^\//, "")}`, {
      headers,
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { data: T };
    return body.data;
  } catch {
    return null;
  }
}
