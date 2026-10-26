// Small fetch wrapper for the Django JSON API (session auth + CSRF cookie).

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function cookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

export async function api(path, { method = "GET", json, form } = {}) {
  const headers = { "X-Requested-With": "fetch" };
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  if (method !== "GET") headers["X-CSRFToken"] = cookie("csrftoken");

  const res = await fetch(path, { method, headers, body, credentials: "same-origin" });
  let data = null;
  try {
    data = await res.json();
  } catch {
    // non-JSON (e.g. a server error page)
  }
  if (!res.ok) throw new ApiError(data?.error || `Something went wrong (${res.status}).`, res.status, data);
  return data;
}
