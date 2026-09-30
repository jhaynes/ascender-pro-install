# Homelab branch notes (epic jhaynes/homelab#121, BUILD-A)

Status: PREPARATION ONLY. No cluster writes, no image pulls beyond
authorized manifest/digest reads, no installer execution (setup.sh is
a rollout-phase live action), no upstream ctrliq PRs/issues/writes.

Upstream base: ctrliq/ascender-pro-install @
67605351acac159bfa73fd4e65ba9f976a909702 (unchanged; the originally
card-pinned ctrliq/ascender-install@a737ea8 remains the Debian
host-support reference — see the f2 table). The fork-base substitution
was confirmed by the scope reviewer: the base repo's ledger path uses
LEDGER_REGISTRY with public-ghcr defaults and cannot install the
entitled Depot Pro images; only this repo carries the DEPOT_REGISTRY
path. #123's owner comment names this repo the execution target.

## Fix-to-defect mapping (authoritative A2 scope)

| # | Defect (verified on 6760535) | Fix | Commit |
|---|---|---|---|
| a | Ingress `tls:` rendered as a sibling key inside spec.rules[0] (invalid per API schema) + namespace-local TLS Secret from tls_crt_path/tls_key_path under https | template: no TLS Secret, no spec.tls, for both k8s_lb_protocol values; Traefik default TLSStore wildcard serves both hostnames | fix(ledger-k3s) |
| b | image refs tag-only (`{{image}}:{{LEDGER_VERSION}}`); digest not expressible | LEDGER_{DB,PARSER,WEB}_IMAGE_REF full-ref override (repo:tag@sha256:…), precedence over registry/tag composition; upstream behavior preserved when unset | fix(ledger-k3s) |
| b2 | no nodeSelector/affinity on the three Pro Deployments while images are linux/amd64-only; db would also schedule on workers without a MariaDB PV | nodeSelector arch=amd64 on db/parser/web; db additionally hostname-pinned via LEDGER_DB_NODE_HOSTNAME (config-fed, no template literal) for deterministic tower-raid5-db binding under WaitForFirstConsumer | fix(ledger-k3s) |
| b3 | a nofail-booted worker with a detached data disk leaves an empty root-filesystem mountpoint — MariaDB would write into the lookalike | fail-closed initContainer (findmnt UUID+FSTYPE vs LEDGER_DB_DATA_FS_UUID, readOnly mount of mysql-data) before the db container | fix(ledger-k3s) |
| c | auth_token debug print; password/token-bearing tasks unlogged; manifests world-readable in tmp_dir | debug task removed; no_log on the five tasks; mode 0600 on both ledger renders (R2: also ascender-deployment-k3s.yml render 0600, ascender-install tmp_dir 0700) | fix(ledger-k3s: secrets) 62996ff |
| c2 | verify_ssl/validate_certs: false flips across the executed k3s chain (22 upstream: ledger_install_k3s 12, ascender_install_k3s 8, install_ledger 1, k8s_setup 1) | all removed on the executed path (verification on); kubernetes.core uses the kubeconfig CA chain (certificate-authority-data; no insecure-skip-tls-verify); uri targets are the DNS-resolved hostnames; LOG_AGGREGATOR_VERIFY_CERT stays false (internal http parser endpoint); upgrade_postgres.yml (maintenance playbook, outside the R4 setup.sh chain) intentionally untouched — tracked as follow-up | fix(ledger-k3s: tls verify) 62996ff + R2 ascender-side |
| d | PVC mysql-data emits no storageClassName (LEDGER_PVC_STORAGE_CLASS documented but never consumed) | conditional storageClassName emission; binds tower-raid5-db via custom.config | fix(ledger-k3s) |
| e | restart-to-pull logic compares LEDGER_VERSION == "latest" (tag-string equality) | digest-aware: restart only when a resolved ref is not digest-pinned | fix(ledger-k3s: tls verify) |
| f | pro common_packages lacks Debian 12/13 keys → KeyError on the Debian 13 installer host | ported from base c8d252c | fix(common) |
| g | digest pins not expressible through the operator's CR surface (hard-coded postgres_image_version: "latest", redis_image_version: "9-alpine"); omitted-version form does NOT pin (R2: operator source + empirical probe — the custom-image branch is skipped, PG falls back to :latest, redis references an undefined version) | additional-spec template: SPLIT-form pins (POSTGRES_IMAGE `repo[:tag]@sha256` + POSTGRES_IMAGE_VERSION `<hex>`; same for REDIS_IMAGE/REDIS_IMAGE_VERSION; EE init image/version split from ASCENDER_EE_IMAGE_REF) so the operator's own `image + ':' + version` concat reconstructs the full digest ref; CR selectors postgres_selector/node_selector rendered when config-defined | feat(ascender-spec) 2704e08 + R2 split-form correction |
| h | ee_images blank-variable validation missing (base #260) | assertions.yml backport | fix(assertions) |

## f2 backport decision table (base a737ea8 vs pro 6760535, all differing fixes)

| Base fix | Decision | Reason |
|---|---|---|
| c8d252c common_packages Debian 12/13 keys | PORT | Debian 13 is the installer-host platform; without it the role KeyErrors |
| c8d252c common role keyring gating (curl/gnupg prereq task, not-k8s_offline AND add_kubernetes_repo gates, pipefail) | PORT | Debian netinst/cloud images ship without curl/gnupg; offline installs previously still fetched the signing key |
| c8d252c setup.sh Debian python3-kubernetes (PEP 668) + preflight + dirname quoting | PORT | `pip install --user` is rejected on Debian 13; sudo's secure_path breaks venv resolution — both break setup.sh on the installer VM |
| c8d252c assertions numeric Debian OS-version compare | PORT | pro base asserts == '24' on the Debian family; Debian 13 cannot pass |
| a737ea8 (#260) ee_images blank-variable validation | PORT | empty/blank ee_images stops the operator from deploying web pods; no-op safety net for our config (ee_images undefined) |
| a1dc7b9/d7f0d00 (#252/#253) setup.sh Enterprise-Linux refusal/epel fixes | SKIP (justified) | RHEL-path only; the installer host is Debian 13 and never enters that branch (the one-line dnf epel fallback rode along with the python-block port) |
| base offline tarball collection bump ctrliq-ascender 25.6.2 | SKIP (justified) | the pro repo pins its own 25.5.1 floor; raising it is upstream's call (recorded caveat: the 25.5.1 collection lacks garbage_collect_secrets handling — operator 25.6.2 is the CR-lifecycle authority) |
| base k8s_setup firewalld Debian-family guard + per-task become on k3s install tasks | SKIP (justified) | all guarded by kube_install: false in our config; k3s never installs via this path (existing cluster) |

## Operator image-concatenation semantics (verified at 25.6.2)

From the operator repo (roles/installer/tasks/database_configuration.yml
:59-68, resources_configuration.yml:236-246, set_images.yml:3-18 at tag
25.6.2, commit db94583 — read directly AND replicated empirically as
verbatim set_fact chains with the fork's CR values):

- A custom postgres/redis/init image ref is composed as
  `image + ':' + version` and is USED only when the image is non-empty
  AND the version is defined and non-empty. Otherwise the operator's
  default tag-composed ref applies (`quay.io/sclorg/postgresql-15-c9s:
  latest` for PG; `ghcr.io/valkey-io/valkey:9-alpine` for redis).
- OMITTED-version digest ref does NOT pin (the R1 branch shape): the PG
  custom-image set_fact is skipped entirely (postgres_image_version is
  undefined) and the effective image falls back to the mutable
  `:latest`; the redis branch's when-clause references the undefined
  version and errors (or renders an invalid trailing-colon ref under
  permissive undefined handling). Probes at R1 demonstrated both.
- SPLIT form DOES pin (the R2 branch shape, empirically verified):
  `postgres_image: quay.io/sclorg/postgresql-15-c9s@sha256` +
  `postgres_image_version: <amd64 child digest hex>` composes to the
  full immutable ref through the operator's own concatenation; same for
  `redis_image: ghcr.io/valkey-io/valkey:9-alpine@sha256` + hex, and the
  EE init container (`image: bare-repo` + `version: tag@sha256:hex`).
  This is how the digest pins are expressed on this branch.
- `control_plane_ee_image` passes through verbatim (no concatenation).
- Caveat for anyone re-probing with ansible-core 2.19+: the operator's
  `when: x | default([]) | length` style conditions are implicit-bool
  conditionals — legal on the operator's bundled core, but they raise
  "Conditional result derived from value of type 'int'" on 2.19
  strictness. That is a local-runner artifact, not operator behavior;
  re-run probes with ANSIBLE_ALLOW_BROKEN_CONDITIONALS=true or an
  operator-bundled core.

The earlier R1 text claiming "empty or omitted version falls back to
the default tag-composed ref, and this is why the digest pins are
expressed as full refs with the version field omitted" was
self-contradictory and wrong on the second half: omitted version does
fall back — which is exactly why it cannot pin. The split form above is
the corrected, verified mechanism.

## A8 operator/CRD lifecycle (for the rollout runbook)

The installer applies the operator via kustomize into the ascender
namespace (cluster-scoped CRDs: AWX/AWXMeshIngress/AWXBackup/AWXRestore
from the operator's config/crd/bases). `garbage_collect_secrets: false`
(our custom.config) makes the operator's cleanup strip ownerReferences
from the admin-password/secret-key/postgres-configuration/
broadcast-websocket/receptor Secrets so they SURVIVE CR deletion
(verified against the operator's own roles/installer/tasks/cleanup.yml
at 25.6.2: the strip runs `when: not garbage_collect_secrets | bool`;
the installer's default is true — dangerous for restore, hence the
override). Scoped rollback: delete the CR first, confirm both static
PVs are Released, then the operator deployment, then the namespace
objects — never CRDs, shared ClusterRoles, the traefik TLSStore or the
wildcard Certificate.

## U3 record (effective default EE at 25.6.2)

With ee_images undefined in custom.config (our config), the CR renders
control_plane_ee_image from k8s_container_registry-defaulted
ghcr.io/ctrliq/ascender-ee:25.6.2 (additional-spec.yml), and the
operator's own ee_images default is the same
ghcr.io/ctrliq/ascender-ee:<version> image (installer-role defaults at
25.6.2) — the multiarch manifest list verified at digest
sha256:c5b300dbeb6405dc068a21d4851b0449ab7b795858656ea7ccc35263fa2aab80
(amd64+arm64). Job pods may therefore run on the arm64 workers; the R4
arm64 probe (one benign job on workers 7/8) covers exactly this default
EE. Any later custom EE takes its own placement check (out of epic
scope).

## U5 record (backup.yml coverage, read per plan D2/MoA-15)

The installer's backup.yml (playbooks/backup.yml → ascender_backup
role) creates an AWXBackup CR, waits for status.backupDirectory +
backupClaim, mounts that claim through a busybox pod, and k8s_cp's
exactly three files out: `tower.db` (the PostgreSQL dump), `secrets.yml`
(the generated Secret material), `awx_object` (the CR state). Coverage
conclusion for BUILD-D: the Ascender/PG side is fully covered
(database + secrets + CR object), but the Pro/ledger side (MariaDB,
ledger Secrets, custom.config) is NOT touched by backup.yml —
BUILD-D's design (separate MariaDB dump + custom.config capture) stands,
with pg_dump tower.db obtainable either through this role or directly;
decision recorded here per plan (D2: BUILD-A records what backup.yml
captures; BUILD-D wraps or falls back).

## Validation

- tests/homelab_render_tests.py — 109/109 assertions PASS (A3.1–A3.10
  with per-task guard and rendered-URL checks, A2b3, A4 additional-spec
  split-form + operator-composition effective-ref checks, CR-selector
  coverage; the R2 round extended the R1 matrix of 89).
- ansible-playbook --syntax-check PASS on setup.yml, install_ledger.yml,
  install_ascender.yml, assertions.yml, kubernetes_setup.yml,
  backup.yml, restore.yml.
- Secret scan of the tracked tree: clean (no credential values, tokens,
  keys; placeholder strings only in tests).
- kubectl --dry-run=client on the rendered manifest: runs on the
  installer VM at rollout (R2/R3 evidence per plan A3.8); the offline
  structural schema variant is in the test matrix.
- R2 mutation battery on the extended matrix (scratch copies only):
  hosts-guard drop, firewalld-guard drop, all-guards drop, rendered
  raw-IP URL, PG digest transposition (ctx-side), CR selector drift,
  EE double-tag regression, omitted-version PG form, reintroduced
  verify_ssl flip — all caught (matrix fails), baselines 109/109.
