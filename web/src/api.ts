export type ChatRequest = {
  message: string;
  conversation_id: string | null;
};

export type ChatResponse = {
  response: string;
  conversation_id: string;
  tool_calls: Array<Record<string, unknown>>;
};

export class AuthenticationError extends Error {
  constructor(message: string, public statusCode?: number) {
    super(message);
    this.name = "AuthenticationError";
  }
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

export async function postChat(
  token: string,
  body: ChatRequest
): Promise<ChatResponse> {
  const response = await fetch(`${apiBaseUrl}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const json = (await response.json()) as { detail?: string };
      if (json?.detail) {
        detail = json.detail;
      }
    } catch {
      // Keep default detail when response body is not JSON.
    }
    
    // Throw AuthenticationError for 401/403 - indicates token expiration or revocation
    if (response.status === 401 || response.status === 403) {
      throw new AuthenticationError(detail, response.status);
    }
    
    throw new Error(detail);
  }

  return (await response.json()) as ChatResponse;
}
