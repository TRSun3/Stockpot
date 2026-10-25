// Talking to the Stockpot API. Every call either returns parsed JSON or throws an ApiError with a readable message.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const OFFLINE = "Can't reach Stockpot. Is the server running?";

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

async function send(method, path, body) {
  try {
    return await fetch(path, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(OFFLINE, 0);
  }
}

export async function api(method, path, body) {
  const response = await send(method, path, body);
  if (!response.ok) throw await failure(response);
  return response.json();
}

// Posts `body` and calls `onEvent` for each server-sent event the reply streams back.
// Throws an ApiError if the connection drops or the stream ends without its closing `done` event.
export async function stream(path, body, onEvent) {
  const response = await send("POST", path, body);
  if (!response.ok) throw await failure(response);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const handle = (block) => {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!data) return;
    let event;
    try {
      event = JSON.parse(data);
    } catch {
      return;
    }
    if (event.type === "done") finished = true;
    onEvent(event);
  };

  for (;;) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch {
      throw new ApiError("The connection dropped before the reply finished.", 0);
    }
    buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done }).replace(/\r\n?/g, "\n");
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      handle(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
    }
    if (chunk.done) break;
  }
  if (buffer.trim()) handle(buffer);
  if (!finished) throw new ApiError("The reply was cut off before it finished.", 0);
}
