export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
  csrf?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(`/api/${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      payload?.error?.message || "请求失败，请稍后重试",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export type Identity = {
  can_curate_public_data: boolean;
  user: { id: string; email: string; full_name: string };
  organizations: {
    id: string;
    name: string;
    role: "owner" | "admin" | "member" | "viewer";
  }[];
  csrf_token: string;
};
export type Project = {
  id: string;
  name: string;
  description: string;
  organization_id: string;
  created_by: string;
  my_role: string;
  can_write: boolean;
  can_manage_members: boolean;
};
export type Member = {
  user_id: string;
  full_name: string;
  email: string;
  role: string;
  is_active: boolean;
  user_is_active?: boolean;
};
export type Audit = {
  id: string;
  action: string;
  actor_id: string;
  resource_id: string;
  result: string;
  created_at: string;
  details: Record<string, unknown>;
};
