# OCI policies for the workshop

This page is for the **tenancy administrator** who prepares the compartment
where the participants work. It lists the IAM policies the workshop needs,
explains why each one is there, and gives the commands to create them.

All the policies are at **compartment level**: nothing is granted in the
whole tenancy.

## Who needs access to what

The workshop uses two different identities, and each one needs its own
policy:

| Identity | What it does | Used by |
|----------|--------------|---------|
| The **participant's OCI user**, through `~/.oci/config` (API key or session token) | Creates the Generative AI project; creates, uses, stops and deletes sandboxes; writes and reads files in them | the OCI CLI (`generative-ai-project create`), the preflight, the agent, `fraud_detective.cleanup` |
| The **OCI Generative AI API key** (`OCI_GENAI_API_KEY` in `.env`) | Calls the model with the Responses API, inside the project (conversations, `previous_response_id`) | the agent of Labs 2–3, the preflight model check, Lab 4 on OCI |

A Generative AI API key is not an OCI IAM user and does not belong to a
group. Its requests have the principal type `generativeaiapikey`, so its
policy uses `any-user` with a `where` condition on that type.

If participants use **OpenAI** for the model, the API key policy is not
needed: only the sandbox and project policies are. Lab 4 with the default
configuration calls OpenAI and needs no OCI policy.

## The policies

Replace `<compartment-ocid>` with the OCID of the workshop compartment and
`fraud-detective-users` with the group of the participants. The statements
use `compartment id`, so they work wherever the policy is attached (the
compartment itself or one of its parents) and are not affected by
compartment names.

### 1. Participants: projects and sandboxes

```text
Allow group fraud-detective-users to manage generative-ai-project in compartment id <compartment-ocid>
Allow group fraud-detective-users to manage generative-ai-sandbox in compartment id <compartment-ocid>
```

These are the two statements that Oracle documents for sandboxes
([Sandbox permissions][sandbox-permissions]).

- **`manage generative-ai-project`**: each participant creates a project
  with conversations, short-term memory and sandboxes enabled (Lab 0). The
  preflight then reads it. If the administrator creates one shared project
  instead, `use generative-ai-project` is enough: Oracle gives it as the
  minimal permission to get a project OCID ([Projects][projects]).
- **`manage generative-ai-sandbox`**: the agent creates the sandbox, runs
  commands in it, and the CLI or `cleanup` deletes it. `use` is **not
  enough**: Oracle states that it does not grant creating or deleting a
  sandbox.

How the sandbox verbs map to the operations ([Sandbox permissions][sandbox-permissions]):

| Verb | Operations | Permission names |
|------|-----------|------------------|
| `inspect` | ListSandboxes | `GENERATIVE_AI_SANDBOX_INSPECT` |
| `read` | + GetSandbox | `GENERATIVE_AI_SANDBOX_READ` |
| `use` | + UpdateSandbox, RunSandboxCommand | `GENERATIVE_AI_SANDBOX_UPDATE`, `GENERATIVE_AI_SANDBOX_USE` |
| `manage` | + CreateSandbox, DeleteSandbox | `GENERATIVE_AI_SANDBOX_CREATE`, `GENERATIVE_AI_SANDBOX_DELETE` |

`manage` grants every operation on the sandboxes of the compartment: the
workshop does not restrict them. Besides creating sandboxes and running
commands, the workshop stops them, writes and reads files in them, can take
snapshots and extend their lifetime.

### 2. Optional: participants create their own API key

If each participant creates their own OCI Generative AI API key in the
compartment ([API key permissions][apikey-permissions]):

```text
Allow group fraud-detective-users to manage generative-ai-apikey in compartment id <compartment-ocid>
```

Skip it if the administrator creates the keys and hands them out.

### 3. The API key: model calls

```text
Allow any-user to use generative-ai-family in compartment id <compartment-ocid> where ALL {request.principal.type='generativeaiapikey'}
```

This is the compartment-level statement that Oracle documents for API keys
([Adding key permissions][add-api-permission]). It lets any Generative AI
API key call the models of the Generative AI family in the compartment,
including the Responses API with the conversations of the project.

To allow only specific keys, add their OCIDs:

```text
Allow any-user to use generative-ai-family in compartment id <compartment-ocid> where ALL {request.principal.type='generativeaiapikey', request.principal.id='<api-key-ocid>'}
```

The workshop does not limit the models. The project calls two of them: the
model in `config/settings.toml` and the compaction model of short-term
memory, `openai.gpt-oss-120b`.

## What the workshop does not need

| Policy | Why it is not needed |
|--------|----------------------|
| `use subnets`, `use network-security-groups` | Only for sandboxes with **custom** networking. The workshop uses `MANAGED` networking with `DENY_ALL` ([Sandbox networking][sandbox-networking]). |
| `read objects`, `read secret-bundles` with `request.principal.type = 'generativeaisandbox'` | Only when code in the sandbox calls other OCI services. Here the sandbox has no outbound access and receives the bundle from the participant's machine. |
| `manage generative-ai-family in tenancy` | Too broad: Oracle recommends it only for administrators or sandbox tenancies ([IAM policies][iam-policies]). |
| Custom image repository access | The workshop uses the standard `python-3.11` runtime. |

## Create the policies

The examples use the OCI CLI as an administrator who can manage policies in
the compartment. The statements go in JSON files, which avoids quoting
problems with the `where` clause.

**1. The participants' group.** Create the group in the Console
(**Identity & Security → Domains → your domain → Groups**) and add the
participants. If the group is not in the `Default` domain, write it in the
statements as `group '<domain-name>'/'fraud-detective-users'`.

**2. The statements.** Save them in two files, replacing the placeholders.
`users-policy.json`:

```json
[
  "Allow group fraud-detective-users to manage generative-ai-project in compartment id <compartment-ocid>",
  "Allow group fraud-detective-users to manage generative-ai-sandbox in compartment id <compartment-ocid>",
  "Allow group fraud-detective-users to manage generative-ai-apikey in compartment id <compartment-ocid>"
]
```

Remove the last line if participants do not create their own keys.

`apikey-policy.json`:

```json
[
  "Allow any-user to use generative-ai-family in compartment id <compartment-ocid> where ALL {request.principal.type='generativeaiapikey'}"
]
```

**3. Create the two policies** in the workshop compartment:

```bash
oci iam policy create \
  --compartment-id <compartment-ocid> \
  --name fraud-detective-users \
  --description "AI Fraud Detective workshop: projects and sandboxes for the participants" \
  --statements file://users-policy.json
```

```bash
oci iam policy create \
  --compartment-id <compartment-ocid> \
  --name fraud-detective-apikeys \
  --description "AI Fraud Detective workshop: model calls with Generative AI API keys" \
  --statements file://apikey-policy.json
```

**4. Check them:**

```bash
oci iam policy list --compartment-id <compartment-ocid> --query "data[?starts_with(name, 'fraud-detective')].{name:name, statements:statements}"
```

New policies can take a few minutes to apply. Then a participant runs the
preflight, which checks the project, the sandbox permissions and a model
call:

```bash
python -m fraud_detective.preflight
```

## Before the workshop

Policies are not the only prerequisite:

- **Region.** The compartment's region must support sandboxes, and the
  project and the sandboxes must be in the same region
  ([Regions for sandboxes][sandbox-regions]). The workshop was tested in
  `eu-frankfurt-1`.
- **Service limits.** The tenancy needs enough sandbox capacity for all the
  participants at the same time: one `SMALL` sandbox (1 OCPU, 4 GB) per
  participant, plus the test sandbox of the preflight
  ([Sandbox limits][sandbox-limits]). Ask for an increase in advance.
- **Models.** The model in `config/settings.toml` and the compaction model
  `openai.gpt-oss-120b` must be available in the region.
- **Network policy.** A project's network policy cannot be changed after
  creation, and sandboxes cannot be disabled once enabled
  ([Creating a project][create-project]). A wrong project must be recreated.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `404 NotAuthorizedOrNotFound` on the project or on the sandboxes | Policy 1 missing, a wrong compartment, or `oci.region` is not the project's region |
| The sandbox can be listed but not created or deleted | `use` instead of `manage` on `generative-ai-sandbox` |
| The model call is refused (`401`, `403` or `404`) | Policy 3 missing, or a wrong or expired key in `.env` |
| `429` when creating sandboxes | Service limits reached: delete leftovers with `python -m fraud_detective.cleanup --delete` |

## Sources

Oracle documentation, read on 2026-11-25. Check it again before each
workshop.

- [IAM policies for OCI Generative AI][iam-policies]
- [Sandbox permissions][sandbox-permissions]
- [Sandbox networking][sandbox-networking]
- [Regions for sandboxes][sandbox-regions]
- [Sandbox limits][sandbox-limits]
- [Creating a project][create-project]
- [Projects][projects]
- [API key permissions][apikey-permissions]
- [Adding key permissions][add-api-permission]

[iam-policies]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/iam-policies.htm
[sandbox-permissions]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/sandbox-permissions.htm
[sandbox-networking]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/sandbox-networking.htm
[sandbox-regions]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/sandbox-regions.htm
[sandbox-limits]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/sandbox-limits.htm
[create-project]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/create-project.htm
[projects]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/projects.htm
[apikey-permissions]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/api-key-permissions.htm
[add-api-permission]: https://docs.oracle.com/en-us/iaas/Content/generative-ai/add-api-permission.htm
