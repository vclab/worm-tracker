// Central API base URL — override with VITE_API_URL env var for non-local deployments
export const API = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
