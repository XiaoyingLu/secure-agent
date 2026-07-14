import React from "react";
import ReactDOM from "react-dom/client";
import { MsalProvider } from "@azure/msal-react";

import App from "./App";
import { msalInstance } from "./msalConfig";
import "./styles.css";

/**
 * Initialize MSAL and handle authentication redirect from Entra ID callback
 */
void msalInstance.initialize().then(() => {
  // Handle redirect from Entra ID after login (required for OAuth flow)
  void msalInstance.handleRedirectPromise().then(() => {
    const account = msalInstance.getAllAccounts()[0] ?? null;
    if (account) {
      msalInstance.setActiveAccount(account);
    }

    ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
      <React.StrictMode>
        <MsalProvider instance={msalInstance}>
          <App />
        </MsalProvider>
      </React.StrictMode>
    );
  });
});
