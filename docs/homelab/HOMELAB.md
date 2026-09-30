# Branch feat/ascender-installer-prep — homelab scope

This branch carries the narrow, homelab-specific corrections to the
pinned upstream installer that epic jhaynes/homelab#121 (Ascender +
Ascender Pro on Tower RAID5) requires before any rollout. It is
preparation only: no cluster writes, no image pulls beyond authorized
manifest/digest reads, no upstream ctrliq PRs.

Upstream base: ctrliq/ascender-pro-install @
67605351acac159bfa73fd4e65ba9f976a909702 (short 6760535), unchanged.
Every commit below is a small, reviewable delta on that pin. The
approved execution plan and its frozen SHA live on the homelab Kanban
board (task t_c0c633de / BUILD-A card t_56cf7644); the fork-base
substitution from the originally pinned ctrliq/ascender-install@a737ea8
was confirmed by the scope reviewer because the base repo's ledger path
cannot install the entitled Depot Pro images.

## Patches (each its own commit)

1. `fix(ledger-k3s-tls)` — stop rendering the namespace-local TLS Secret
   and the misplaced `spec.tls`/rules sibling; the homelab Traefik
   default TLSStore wildcard serves both hostnames.
2. `fix(ledger-k3s-arch)` — pin db/parser/web Deployments to
   linux/amd64; db additionally pinned to k3s-worker-5 (hostname) for
   deterministic binding under WaitForFirstConsumer.
3. `fix(ledger-k3s-secrets)` — remove the auth_token debug task, add
   no_log to the five password/token-bearing tasks, mode 0600 on the
   two credential-bearing manifest renders.
4. `feat(ledger-pvc-class)` — emit storageClassName from
   LEDGER_PVC_STORAGE_CLASS in the mysql-data PVC.
5. `feat(ledger-image-refs)` — digest-capable image refs
   (LEDGER_{DB,PARSER,WEB}_IMAGE_REF) + digest-aware restart logic.
6. `feat(ledger-mariadb-failclosed)` — fail-closed initContainer that
   verifies the mysql-data mount by per-host UUID+FSTYPE before the
   db container starts.
7. `fix(ledger-k3s-tls-verify)` — drop verify_ssl/validate_certs: false
   from the kubernetes.core/uri tasks in ledger_install_k3s.yml.
8. `feat(ascender-spec-image-refs)` — digest-capable postgres/redis/
   control-plane-EE refs in the CR additional-spec template (operator
   25.6.2 concatenates image+":"+version when a version is supplied;
   empty version yields the bare ref — verified from
   roles/installer/tasks/{database_configuration,resources_configuration,set_images}.yml
   at 25.6.2).
9. `fix(ee-images-validation)` — backport of the blank-ee_images
   validation from base a737ea8 (f2 backport decision table in
   docs/homelab/HOMELAB.md).
10. `fix(common-debian13)` — backport of base c8d252c's Debian 12/13
    common_packages keys (Debian 13 is the homelab installer-host
    platform).
11. `fix(setup-debian)` — backport of base c8d252c's setup.sh Debian
    fixes (PEP 668 python3-kubernetes, preflight ansible check, quoting).

See docs/homelab/HOMELAB.md for the full fix-to-defect mapping, the
f2 backport decision table, and the frozen release set with full
digests.
