# Homelab frozen release set (epic #121 / BUILD-A)

Pinned by the approved execution plan (task t_c0c633de, plan SHA-256
d1d8e3f96e75e88750b7ef3f0ea23cedc8fd23fb8d3abad91d91ab007ea9f1f6, A4).
Digests verified against the registries at plan time (Depot reads via
the authorized Smithers-source credentials; ghcr/quay public manifest
reads). FULL digests — a frozen set is not freezable truncated.

| Component | Pinned ref | Full digest | Source |
|---|---|---|---|
| Pro web | depot.ciq.com/ascender-pro/ascender-ledger-pro-images/ledger-web:v1.1.2 | sha256:214342bf88da9f5eafc209b99d0dece7ec7f20369c40beb0235a0e2d65ef0f80 | plan E4 (Depot manifest read; byte-verified by the scope reviewer) |
| Pro parser | depot.ciq.com/ascender-pro/ascender-ledger-pro-images/ledger-parser:v1.1.2 | sha256:5fe345af9f0c09590665f4eb1a4b1d8198a2c6898cd2bdd797ae32b978cd5ea3 | plan E4 |
| Pro db | depot.ciq.com/ascender-pro/ascender-ledger-pro-images/ledger-db:v1.1.2 | sha256:0cd24c0f7c3fed6bc4ce69e7e7dc027b587f28e595a76a9510669d8fc5c13668 | plan E4 |
| Ascender | ghcr.io/ctrliq/ascender:25.6.2 | sha256:7f7dec7756285d46f5fb28c4bd03d0728571eeb1f969356dea46d3b003fe9ace (multiarch index) | plan E5 |
| Ascender EE | ghcr.io/ctrliq/ascender-ee:25.6.2 | sha256:c5b300dbeb6405dc068a21d4851b0449ab7b795858656ea7ccc35263fa2aab80 (manifest list) | plan E5 |
| Operator | ghcr.io/ctrliq/ascender-operator:25.6.2 (kustomize ref 25.6.2) | sha256:3486e347088dc0c0bd42bcda35b59a8b3bbf3638d2ab9c4cd0e3f9440af842df (multiarch index) | plan E5 |
| PostgreSQL (operator-managed) | quay.io/sclorg/postgresql-15-c9s | latest index digest sha256:3a850891945146b7b69fa52da1b118c265ef67bc0106524f4b3c94df2b470b9b (multiarch) | plan E5 |
| Valkey | ghcr.io/valkey-io/valkey:9-alpine | sha256:48332870af354a799964c0012ae1194a0bf2bf894eb508f945810596dc2d8d11 (multiarch index) | plan E5 |

## How each pin is expressed at install time

- Pro web/parser/db: `LEDGER_{WEB,PARSER,DB}_IMAGE_REF` in custom.config,
  each `repo:v1.1.2@sha256:<digest>` — valid OCI tag+digest form (keeps
  the human-readable tag while pinning by digest). `LEDGER_VERSION`
  stays `v1.1.2` for the role's non-restart logic; the restart-to-pull
  condition is digest-aware on this branch.
- PostgreSQL: the operator 25.6.2 composes `postgres_image` + ':' +
  `postgres_image_version` only when the version is non-empty (verified
  in its roles/installer/tasks/database_configuration.yml). Pin form:
  `POSTGRES_IMAGE: quay.io/sclorg/postgresql-15-c9s@sha256:<amd64 child
  digest>` with `POSTGRES_IMAGE_VERSION` left undefined (this branch's
  additional-spec template omits the line when undefined, so the custom
  ref passes through whole). The amd64 child-manifest digest is
  recorded by the wrapper role at rollout time from the multiarch index
  (authorized manifest read); the postgres_selector hostname pin makes
  the runtime node amd64 either way.
- Valkey: same mechanism (`REDIS_IMAGE` full digest ref,
  `REDIS_IMAGE_VERSION` undefined).
- Ascender EE / init container: `ASCENDER_EE_IMAGE_REF` full digest ref
  (control_plane_ee_image passes through verbatim in the operator; the
  init container's image/version fields are split from the same ref).
- Operator image: kustomize `newTag` is pinned by
  `ASCENDER_OPERATOR_VERSION` (25.6.2); the full digest above is
  asserted at rollout R4d from the running pod imageIDs.
- Ascender app image: `ASCENDER_IMAGE` + `ASCENDER_VERSION` (25.6.2)
  tag composition via the CR (`image`/`image_version` fields); the full
  digest above is asserted at rollout R4d from the running pod
  imageIDs.

## Compatibility basis

The pro installer's own defaults pin Ascender 25.6.2 + operator 25.6.2
together (default.config.yml / group_vars), and Pro v1.1.2 is the
current subscription release line (plan E4/E6). No published
Pro<->Ascender compatibility matrix exists beyond the installer's own
pairing — that pairing IS the vendor's integration contract (plan A4).
Explicit fallback if reviewers require more: CIQ support ticket
(recorded as plan P5; not blocking).

## Pull policy

`ascender_image_pull_policy: IfNotPresent` for digest-pinned refs
(installer default `Always` was chosen for mutable tags; plan A2h). The
operator's own default pull policy is already IfNotPresent.

## Known caveats (from the scope review, for the record)

1. The Galaxy collection `ctrliq.ascender:25.5.1` (the installer's
   pinned floor) contains no `garbage_collect_secrets` handling; the
   semantics verified for that flag come from the operator repo at
   25.6.2, which is the correct authority for CR-lifecycle behavior.
   The 25.5.1-floor vs ASCENDER 25.6.2 pairing is the vendor's own
   contract per the plan; no fork change required.
2. MariaDB major version inside ledger-db:v1.1.2 is not declared in
   the image config (entrypoint script only — reading it is a layer
   blob download, outside this card's authorized manifest-read scope);
   verified at rollout R4 first pod exec. mariadb-dump
   --single-transaction is stable across MariaDB 10/11.
