# Entra ID App Registration

This app registration represents the enterprise AI agent API and authorizes
delegated user access only. Microsoft Graph calls must continue to use the
On-Behalf-Of flow so Graph enforces the signed-in user's permissions.

## Registration Metadata

| Field | Value |
|---|---|
| Display name | `secure-agent-enterprise-ai-agent` |
| Application (client) ID | Set `ENTRA_CLIENT_ID` from the app registration overview |
| Directory (tenant) ID | Set `ENTRA_TENANT_ID` from the app registration overview |
| Supported account types | Single tenant |

Do not document client secrets here. Store any development client secret in
Key Vault as `ENTRA-CLIENT-SECRET` or in local `.env.local` as
`ENTRA_CLIENT_SECRET`.

## Required Delegated Scopes

Configure these Microsoft Graph delegated API permissions and grant admin
consent for the tenant:

| API | Delegated permission | Reason |
|---|---|---|
| Microsoft Graph | `User.Read` | Read the signed-in user's profile and validate user context. |
| Microsoft Graph | `Mail.Read` | Read messages available to the signed-in user. |
| Microsoft Graph | `Calendars.Read` | Read calendar events available to the signed-in user. |
| Microsoft Graph | `Sites.Read.All` | Search SharePoint and OneDrive files available to the signed-in user. |

The app API should also expose a delegated scope:

| Scope | Admin consent display name |
|---|---|
| `api://<ENTRA_CLIENT_ID>/access_as_user` | Access secure-agent as the signed-in user |

For local configuration, set:

```env
ENTRA_DELEGATED_SCOPES=User.Read,Mail.Read,Calendars.Read,Sites.Read.All,api://<ENTRA_CLIENT_ID>/access_as_user
```

## Redirect URIs

Register the following Web redirect URIs:

| Environment | Redirect URI |
|---|---|
| Local development | `http://127.0.0.1:8000/callback` |
| Production | `https://<agent-api-host>/callback` |

For local configuration, set:

```env
ENTRA_REDIRECT_URIS=http://127.0.0.1:8000/callback,https://<agent-api-host>/callback
```

Keep redirect URIs exact. Entra ID validates scheme, host, path, and port.
