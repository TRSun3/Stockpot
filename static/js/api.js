// Talking to the Stockpot API. Every call either returns parsed JSON or throws an ApiError with a readable message.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function failure(response) {
  let message = `Something went wrong (${response.status}).`;
  try {
    const body = await response.json();
    if (body && body.error) message = body.error;
  } catch {
    // The body wasn't JSON; keep the generic message.
  }
  if (response.status === 401) document.dispatchEvent(new CustomEvent("auth:lost"));
  return new ApiError(message, response.status);
}

export async function api(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach Stockpot. Is the server running?", 0);
  }
  if (!response.ok) throw await failure(response);
  return response.json();
}

// Posts `body` and calls `onEvent` for each server-sent event the reply streams back.
export async function stream(path, body, onEvent) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach Stockpot. Is the server running?", 0);
  }
  if (!response.ok) throw await failure(response);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      if (raw.startsWith("data: ")) onEvent(JSON.parse(raw.slice(6)));
    }
  }
}
