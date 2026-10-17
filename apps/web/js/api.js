// Thin fetch wrapper. All views go through this so errors are uniform:
// a failed call throws ApiError whose .message is the server's `detail`.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(method, path, body, { raw = false } = {}) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError('Không kết nối được máy chủ ChurchMix. Kiểm tra server đang chạy.', 0, null);
  }

  if (raw) {
    if (!res.ok) throw new ApiError(`Lỗi ${res.status}`, res.status, null);
    return res;
  }

  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }

  if (!res.ok) {
    let detail = (data && (data.detail || data.message)) || res.statusText || `Lỗi ${res.status}`;
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    throw new ApiError(String(detail), res.status, data);
  }
  return data;
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body = {}) => request('POST', path, body),
  put: (path, body = {}) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
  upload: (path, formData) => request('POST', path, formData),
  raw: (path) => request('GET', path, undefined, { raw: true }),
};

// Operator identity used for every approval / audit entry.
const OP_KEY = 'churchmix.operator';
export function getOperator() {
  try { return localStorage.getItem(OP_KEY) || 'Kỹ thuật viên'; } catch { return 'Kỹ thuật viên'; }
}
export function setOperator(name) {
  try { localStorage.setItem(OP_KEY, name.trim() || 'Kỹ thuật viên'); } catch { /* storage blocked */ }
}
