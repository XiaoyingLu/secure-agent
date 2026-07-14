import { FormEvent, useMemo, useState, useEffect } from "react";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { InteractionRequiredAuthError } from "@azure/msal-browser";

import { postChat, AuthenticationError } from "./api";
import { acquireApiToken, hasMsalConfig, loginRequest } from "./msalConfig";

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
};

function describeAuthError(error: unknown): string {
  const fallback = "Sign-in failed. Check your MSAL and Entra app registration settings.";
  if (!(error instanceof Error)) {
    return fallback;
  }

  const details = error.message;
  if (details.includes("AADSTS9002326")) {
    return [
      "AADSTS9002326: The configured client is not registered as a Single-page application (SPA).",
      "In Entra app registration, open Authentication and add SPA redirect URI http://localhost:5173.",
      "Also set VITE_API_SCOPE to your API scope (for example api://<api-app-client-id>/access_as_user)."
    ].join(" ");
  }

  return details || fallback;
}

export default function App() {
  const { instance, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);

  const signedInUser = useMemo(() => accounts[0]?.username ?? "", [accounts]);

  // Ensure active account is set when accounts change
  useEffect(() => {
    if (accounts.length > 0 && !instance.getActiveAccount()) {
      instance.setActiveAccount(accounts[0] ?? null);
    }
  }, [accounts, instance]);

  async function handleLogin() {
    setError(null);
    try {
      await instance.loginPopup(loginRequest);
      // After successful login, accounts should be updated automatically
      // through the MSAL context and hooks
      const activeAccount = instance.getAllAccounts()[0] ?? null;
      if (activeAccount) {
        instance.setActiveAccount(activeAccount);
      }
    } catch (loginError: unknown) {
      setError(describeAuthError(loginError));
    }
  }

  function handleLogout() {
    setConversationId(null);
    setMessages([]);
    setInput("");
    setError(null);
    void instance.logoutPopup();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!input.trim() || isSending) {
      return;
    }

    const message = input.trim();
    setInput("");
    setError(null);
    setIsSending(true);
    setMessages((previous) => [...previous, { role: "user", text: message }]);

    try {
      const token = await acquireApiToken();
      const response = await postChat(token, {
        message,
        conversation_id: conversationId
      });

      setConversationId(response.conversation_id);
      setMessages((previous) => [
        ...previous,
        { role: "assistant", text: response.response }
      ]);
    } catch (submitError: unknown) {
      let detail = submitError instanceof Error ? submitError.message : "Unexpected error";
      
      // Check if this is an authentication/token expiration error
      const isAuthError = 
        submitError instanceof AuthenticationError ||
        (submitError instanceof InteractionRequiredAuthError) ||
        (submitError instanceof Error && (
          submitError.message.includes("No signed-in account found") ||
          submitError.message.includes("token") ||
          submitError.message.includes("unauthorized")
        ));

      if (isAuthError) {
        // Auto-logout on token expiration or authentication failure
        detail = "Your session has expired. Please sign in again.";
        handleLogout();
      }
      
      setError(detail);
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          text: "I hit an error while sending your message. Please try again."
        }
      ]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Secure Agent</p>
          <h1>Chat</h1>
        </div>
        <div className="auth-controls">
          {isAuthenticated ? (
            <>
              <span className="user-pill">{signedInUser}</span>
              <button className="ghost" type="button" onClick={handleLogout}>
                Sign out
              </button>
            </>
          ) : (
            <button type="button" onClick={handleLogin} disabled={!hasMsalConfig}>
              Sign in with Microsoft
            </button>
          )}
        </div>
      </header>

      <main className="chat-panel" aria-live="polite">
        {!hasMsalConfig ? (
          <p className="notice">
            Missing MSAL configuration. Set VITE_ENTRA_TENANT_ID,
            VITE_ENTRA_CLIENT_ID, and VITE_API_SCOPE in web/.env.local.
          </p>
        ) : null}

        {messages.length === 0 ? (
          <p className="notice">
            Ask about your Microsoft 365 data once signed in.
          </p>
        ) : (
          <ul className="message-list">
            {messages.map((message, index) => (
              <li key={`${message.role}-${index}`} className={`message ${message.role}`}>
                <p>{message.text}</p>
              </li>
            ))}
          </ul>
        )}
      </main>

      {error ? <p className="error-banner">{error}</p> : null}

      <form className="composer" onSubmit={handleSubmit}>
        <label htmlFor="chat-input" className="visually-hidden">
          Your message
        </label>
        <textarea
          id="chat-input"
          placeholder={
            isAuthenticated
              ? "Type your question..."
              : "Sign in first to start chatting"
          }
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={3}
          disabled={!isAuthenticated || isSending}
        />
        <button type="submit" disabled={!isAuthenticated || isSending || !input.trim()}>
          {isSending ? "Sending..." : "Send"}
        </button>
      </form>
    </div>
  );
}
