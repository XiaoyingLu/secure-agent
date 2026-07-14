import {
  Configuration,
  InteractionRequiredAuthError,
  PopupRequest,
  PublicClientApplication,
  SilentRequest
} from "@azure/msal-browser";

const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID;
const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID;
const configuredScope = import.meta.env.VITE_API_SCOPE;

export const hasMsalConfig = Boolean(tenantId && clientId && configuredScope);

const apiScope = configuredScope || "";

const msalConfig: Configuration = {
  auth: {
    clientId: clientId || "",
    authority: tenantId
      ? `https://login.microsoftonline.com/${tenantId}`
      : "https://login.microsoftonline.com/common",
    redirectUri: window.location.origin
  },
  cache: {
    cacheLocation: "sessionStorage"
  }
};

export const loginRequest: PopupRequest = {
  scopes: apiScope ? [apiScope] : []
};

export const tokenRequest: SilentRequest = {
  scopes: apiScope ? [apiScope] : []
};

export const msalInstance = new PublicClientApplication(msalConfig);

export async function acquireApiToken(): Promise<string> {
  const account = msalInstance.getActiveAccount() || msalInstance.getAllAccounts()[0] || null;
  if (!account) {
    throw new Error("No signed-in account found. Please sign in.");
  }

  msalInstance.setActiveAccount(account);

  try {
    const token = await msalInstance.acquireTokenSilent({
      ...tokenRequest,
      account
    });
    return token.accessToken;
  } catch (error: unknown) {
    if (error instanceof InteractionRequiredAuthError) {
      try {
        const token = await msalInstance.acquireTokenPopup({
          ...loginRequest,
          account
        });
        return token.accessToken;
      } catch (popupError: unknown) {
        // If interactive login also fails, user needs to sign in again
        throw new Error("Failed to refresh authentication. Please sign in again.");
      }
    }
    // Re-throw other errors with a clear message
    if (error instanceof Error) {
      throw new Error(`Token acquisition failed: ${error.message}`);
    }
    throw error;
  }
}
