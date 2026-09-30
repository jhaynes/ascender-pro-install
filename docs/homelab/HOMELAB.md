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
| c | auth_token debug print; password/token-bearing tasks unlogged; manifests world-readable in tmp_dir | debug task removed; no_log on the five tasks; mode 0600 on both renders | fix(ledger-k3s: secrets) |
| c2 | verify_ssl/validate_certs: false on every kubernetes.core/uri task (14 flips) | all flips removed (verification on); kubernetes.core uses the kubeconfig CA chain; uri targets are the DNS-resolved hostnames; LOG_AGGREGATOR_VERIFY_CERT stays false (internal http parser endpoint) | fix(ledger-k3s: tls verify) |
| d | PVC mysql-data emits no storageClassName (LEDGER_PVC_STORAGE_CLASS documented but never consumed) | conditional storageClassName emission; binds tower-raid5-db via custom.config | fix(ledger-k3s) |
| e | restart-to-pull logic compares LEDGER_VERSION == "latest" (tag-string equality) | digest-aware: restart only when a resolved ref is not digest-pinned | fix(ledger-k3s: tls verify) |
| f | pro common_packages lacks Debian 12/13 keys → KeyError on the Debian 13 installer host | ported from base c8d252c | fix(common) |
| g | digest pins not expressible through the operator's CR surface (hard-coded postgres_image_version: "latest", redis_image_version: "9-alpine") | additional-spec template: POSTGRES_IMAGE/REDIS_IMAGE/ASCENDER_EE_IMAGE_REF overrides, version lines templated out when undefined (operator 25.6.2 concatenation compatible) | feat(ascender-spec) |
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

From the operator repo (roles/installer/tasks/database_configuration.yml,
resources_configuration.yml, set_images.yml at tag 25.6.2): a custom
postgres or redis image is composed as `image + ':' + version` only
when the version is non-empty AND the image is non-empty; an empty or
omitted version falls back to the default tag-composed ref.
control_plane_ee_image passes through verbatim (no concatenation).
This is why the digest pins are expressed as full refs with the
version field omitted (template drops the line when undefined).

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

- tests/homelab_render_tests.py — 89/89 assertions PASS (A3.1–A3.10,
  A2b3, A4 additional-spec; see the test commit message for the matrix).
- ansible-playbook --syntax-check PASS on setup.yml, install_ledger.yml,
  install_ascender.yml, assertions.yml, kubernetes_setup.yml,
  backup.yml, restore.yml.
- Secret scan of the tracked tree: clean (no credential values, tokens,
  keys; placeholder strings only in tests).
- kubectl --dry-run=client on the rendered manifest: runs on the
  installer VM at rollout (R2/R3 evidence per plan A3.8); the offline
  structural schema variant is in the test matrix.
