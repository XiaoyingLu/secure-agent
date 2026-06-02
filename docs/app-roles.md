# Entra ID App Roles

Application roles are defined on the **secure-agent** app registration. After a user is assigned a role, Entra includes the role **display name** in the JWT `roles` claim (array of strings). The **App Role ID** is the immutable GUID from the app manifest and is used for assignment APIs and automation—not typically sent in the token.

| Role | App Role ID | JWT `roles` value | Description |
|------|-------------|-------------------|-------------|
| **AgentUser** | Configure as `AGENT_USER_ROLE_ID` | `AgentUser` | Standard users who can invoke the agent chat API and query their own Microsoft 365 data through delegated permissions. |
| **AgentAdmin** | Configure as `AGENT_ADMIN_ROLE_ID` | `AgentAdmin` | Administrators who can manage agent configuration, view audit logs, and access operational endpoints reserved for elevated operators. |

## Assignment

1. In **Microsoft Entra ID** → **App registrations** → **secure-agent** → **App roles**, confirm the roles above exist.
2. Assign users or groups under **Enterprise applications** → **secure-agent** → **Users and groups** → **Assign user/group**.
3. Ensure the API exposes the `roles` optional claim on access tokens (Token configuration → Add optional claim → `roles`).
4. Set `AGENT_USER_ROLE_ID` and `AGENT_ADMIN_ROLE_ID` from the immutable App Role IDs in the app manifest.

## Authorization in this API

- `POST /chat` requires the **AgentUser** role (`require_role("AgentUser")`).
- Additional routes may require **AgentAdmin** via `require_role("AgentAdmin")` in `src/auth/rbac.py`.

Role name constants are defined in code as `AGENT_USER_ROLE_NAME` and `AGENT_ADMIN_ROLE_NAME` in `src/auth/rbac.py`. Matching `*_ROLE_ID` values are loaded from the environment.
