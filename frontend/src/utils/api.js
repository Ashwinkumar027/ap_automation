// AP Automation API & Helper Service

export function getCsrfToken() {
  return window.csrf_token || (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || "";
}

export async function frappeCall(method, args = {}) {
  const headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Frappe-CSRF-Token": getCsrfToken(),
  };

  try {
    const response = await fetch(`/api/method/${method}`, {
      method: "POST",
      headers,
      body: JSON.stringify(args),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err._server_messages ? parseServerMessages(err._server_messages) : (err.message || response.statusText));
    }

    const data = await response.json();
    return data.message !== undefined ? data.message : data;
  } catch (err) {
    console.error(`API Call failed [${method}]:`, err);
    throw err;
  }
}

export async function frappeGetDocList(doctype, { fields = ["*"], filters = {}, limit = 50, order_by = "modified desc" } = {}) {
  const params = new URLSearchParams({
    doctype,
    fields: JSON.stringify(fields),
    filters: JSON.stringify(filters),
    limit_page_length: String(limit),
    order_by,
  });

  const response = await fetch(`/api/resource/${doctype}?${params.toString()}`, {
    headers: {
      "Accept": "application/json",
      "X-Frappe-CSRF-Token": getCsrfToken(),
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to load ${doctype}`);
  }

  const json = await response.json();
  return json.data || [];
}

function parseServerMessages(msgString) {
  try {
    const list = JSON.parse(msgString);
    return list.map(m => {
      try { return JSON.parse(m).message; } catch { return m; }
    }).join("\n");
  } catch {
    return msgString;
  }
}

export function formatMoney(val) {
  return "₹" + Number(val || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

export function initials(name) {
  if (!name) return "AP";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(x => x[0])
    .join("")
    .toUpperCase();
}

export function formatDate(dateStr) {
  if (!dateStr) return "—";
  // Convert YYYY-MM-DD to DD-MM-YYYY
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    const [y, m, d] = dateStr.split("-");
    return `${d}-${m}-${y}`;
  }
  return dateStr;
}

