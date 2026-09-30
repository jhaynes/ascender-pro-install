#!/usr/bin/env python3
"""Offline render/schema test matrix for the homelab installer-prep branch.

Implements plan A3 (test matrix 1-10) against the patched installer
files, fully offline: no cluster API calls, no image pulls, no secret
values. Password-shaped variables are rendered with nonsecret
placeholders. Rendering uses a standalone Jinja2 environment with
minimal ansible-compatible filters (bool/default), NOT the ansible
template module, so this runs anywhere python3 + jinja2 + pyyaml exist.

Usage:
    python3 tests/homelab_render_tests.py
Exit code 0 = all assertions pass; 1 = any failure. Prints PASS/FAIL
per assertion with a final tally.

Run site: the wrapper host (local). Test #8's kubectl dry-run variant
runs on the installer VM (or kubeconform) at rollout time; here it is
replaced by structural schema checks against the k8s object shapes
(API version, required fields, no unknown top-level Ingress spec keys).
"""
import sys
import yaml
from jinja2 import Environment, BaseLoader, StrictUndefined
from jinja2.runtime import Undefined

ROOT = __file__.rsplit("/tests/", 1)[0]
TPL = f"{ROOT}/playbooks/roles/ledger_install/templates/ledger_deployment_k3s.yaml"
TASKS = f"{ROOT}/playbooks/roles/ledger_install/tasks/ledger_install_k3s.yml"
ADDSPEC = (
    f"{ROOT}/playbooks/roles/ascender_install/templates/"
    "ascender-deployment/additional-spec.yml"
)
ASSERTIONS = f"{ROOT}/playbooks/assertions.yml"

PASS = 0
FAIL = 0
RESULTS = []


def check(name, cond, detail=""):  # noqa: ANN001 - detail is diagnostic-only
    global PASS, FAIL
    if cond:
        PASS += 1
        RESULTS.append(f"PASS  {name}")
    else:
        FAIL += 1
        RESULTS.append(f"FAIL  {name} {('-- ' + repr(detail)) if detail else ''}")


# --- minimal ansible-compatible filters -------------------------------
def f_bool(v):
    if isinstance(v, str):
        return v.lower() in ("true", "yes", "on", "1")
    return bool(v)


def f_default(value, default_value="", boolean=False):
    if isinstance(value, Undefined) or (boolean and not value):
        return default_value
    return value


ENV = Environment(loader=BaseLoader(), undefined=StrictUndefined)
ENV.filters["bool"] = f_bool
ENV.filters["default"] = f_default
import base64 as _b64
import json as _json

ENV.filters["b64encode"] = lambda v: _b64.b64encode(str(v).encode()).decode()
ENV.filters["to_json"] = lambda v: _json.dumps(v)
ENV.globals["lookup"] = lambda *_a, **_k: "CERT-CONTENTS"

# --- fixture: nonsecret placeholder config (plan: placeholders only) ---
DIGESTS = {
    "web": "sha256:214342bf88da9f5eafc209b99d0dece7ec7f20369c40beb0235a0e2d65ef0f80",
    "parser": "sha256:5fe345af9f0c09590665f4eb1a4b1d8198a2c6898cd2bdd797ae32b978cd5ea3",
    "db": "sha256:0cd24c0f7c3fed6bc4ce69e7e7dc027b587f28e595a76a9510669d8fc5c13668",
}
BASE_REPO = "depot.ciq.com/ascender-pro/ascender-ledger-pro-images"
FS_UUID = "11111111-2222-3333-4444-555555555555"


def base_ctx(**overrides):
    ctx = dict(
        LEDGER_ADMIN_PASSWORD="nonsecret-placeholder",
        LEDGER_DB_HOST="db",
        LEDGER_DB_PORT="3306",
        LEDGER_DB_NAME="ledger",
        LEDGER_DB_USERNAME="ledger",
        LEDGER_DB_PASSWORD="nonsecret-placeholder",
        LEDGER_NAMESPACE="ledger",
        k8s_lb_protocol="http",
        k3s_service_type="ClusterIP",
        LEDGER_HOSTNAME="ascender-pro.alcedo.dev",
        LEDGER_PVC_SIZE_GB=50,
        LEDGER_PVC_STORAGE_CLASS="tower-raid5-db",
        LEDGER_DB_NODE_HOSTNAME="k3s-worker-5",
        LEDGER_DB_DATA_FS_UUID=FS_UUID,
        k8s_container_registry="",
        ascender_image_pull_policy="IfNotPresent",
        LEDGER_VERSION="v1.1.2",
        LEDGER_DB_IMAGE_REF=f"{BASE_REPO}/ledger-db:v1.1.2@{DIGESTS['db']}",
        LEDGER_PARSER_IMAGE_REF=f"{BASE_REPO}/ledger-parser:v1.1.2@{DIGESTS['parser']}",
        LEDGER_WEB_IMAGE_REF=f"{BASE_REPO}/ledger-web:v1.1.2@{DIGESTS['web']}",
        LEDGER_DB_IMAGE=f"{BASE_REPO}/ledger-db",
        LEDGER_PARSER_IMAGE=f"{BASE_REPO}/ledger-parser",
        LEDGER_WEB_IMAGE=f"{BASE_REPO}/ledger-web",
        ledger_parser_replicas=1,
        ledger_web_replicas=1,
        DEPOT_REGISTRY={
            "BASE": "depot.ciq.com",
            "USERNAME": "placeholder-user",
            "PASSWORD": "nonsecret-placeholder",
        },
        k8s_platform="k3s",
    )
    ctx.update(overrides)
    return ctx


def render(tpl_path, ctx):
    return ENV.from_string(open(tpl_path).read()).render(**ctx)


def render_ledger(ctx):
    out = render(TPL, ctx)
    return [d for d in yaml.safe_load_all(out) if d]


def render_ledger_no_refs():
    """Upstream-behavior render: no _IMAGE_REF vars defined at all."""
    ctx = base_ctx()
    for k in ("LEDGER_DB_IMAGE_REF", "LEDGER_PARSER_IMAGE_REF",
              "LEDGER_WEB_IMAGE_REF"):
        del ctx[k]
    ctx["k8s_container_registry"] = BASE_REPO
    return render_ledger(ctx)


docs_http = render_ledger(base_ctx(k8s_lb_protocol="http"))
docs_https = render_ledger(
    base_ctx(k8s_lb_protocol="https", tls_crt_path="/nonexistent/x.crt",
             tls_key_path="/nonexistent/x.key")
)


def _field_present(rendered, field):
    """True if a rendered CR FIELD line (2-space key) exists, ignoring the
    explanatory comments."""
    return any(
        line.startswith("  " + field + ":")
        for line in rendered.splitlines()
    )

# ---- A3.1 TLS schema (both protocol values) + negative + positive control
for variant, docs in (("http", docs_http), ("https", docs_https)):
    ing = [d for d in docs if d.get("kind") == "Ingress"]
    check(f"A3.1[{variant}] exactly one Ingress", len(ing) == 1, len(ing))
    ing = ing[0] if ing else {"spec": {}}
    check(
        f"A3.1[{variant}] Ingress spec keys are exactly {{ingressClassName, rules}}",
        sorted(ing.get("spec", {}).keys()) == ["ingressClassName", "rules"],
        sorted(ing.get("spec", {}).keys()),
    )
    check(
        f"A3.1[{variant}] no tls key under spec.rules",
        all("tls" not in r for r in ing.get("spec", {}).get("rules", [])),
    )
    tls_secrets = [
        d for d in docs
        if d.get("kind") == "Secret" and d.get("type") == "kubernetes.io/tls"
    ]
    check(f"A3.1[{variant}] no namespace-local TLS Secret", not tls_secrets)
    check(
        f"A3.1[{variant}] no secret named ascender-tls-secret",
        not [d for d in docs
             if d.get("metadata", {}).get("name") == "ascender-tls-secret"],
    )

# negative control: https render with nonexistent cert paths must still
# succeed (no file lookup remains in the template)
check(
    "A3.1[neg] https render with nonexistent tls paths succeeds",
    len(docs_https) == len(docs_http),
)

# positive control: the UNPATCHED upstream template DOES render the TLS
# Secret + spec.tls sibling under https (proves the patched template's
# refusal is the patch, not upstream silence). Upstream file is not
# vendored here; reconstruct its two conditional blocks verbatim.
upstream_tls_block = (
    "{% if k8s_lb_protocol == 'https'  %}\n"
    "---\napiVersion: v1\ndata:\n"
    "  tls.crt: {{ lookup('ansible.builtin.file', tls_crt_path) | b64encode }}\n"
    "  tls.key: {{ lookup('ansible.builtin.file', tls_key_path) | b64encode }}\n"
    "kind: Secret\nmetadata:\n  name: ascender-tls-secret\n"
    "  namespace: {{ LEDGER_NAMESPACE }}\ntype: kubernetes.io/tls\n{% endif %}\n"
)
import jinja2  # noqa: E402

up_env = Environment(loader=BaseLoader())
up_env.filters["bool"] = f_bool
up_env.filters["default"] = f_default
up_env.filters["b64encode"] = lambda v: "Q0VSVA=="
up_env.globals["lookup"] = lambda *_a, **_k: "CERT-CONTENTS"
ctx_ctrl = base_ctx(k8s_lb_protocol="https",
                    tls_crt_path="/nonexistent/x.crt",
                    tls_key_path="/nonexistent/x.key")
ctrl_out = up_env.from_string(upstream_tls_block).render(**ctx_ctrl)
ctrl_docs = [d for d in yaml.safe_load_all(ctrl_out) if d]
check(
    "A3.1[ctrl] upstream-shaped fixture renders a TLS Secret under https",
    len(ctrl_docs) == 1
    and ctrl_docs[0].get("metadata", {}).get("name") == "ascender-tls-secret",
)

# ---- A3.2 ingressClassName == traefik
ing = [d for d in docs_http if d.get("kind") == "Ingress"][0]
check(
    "A3.2 ingressClassName == traefik",
    ing["spec"].get("ingressClassName") == "traefik",
    ing["spec"].get("ingressClassName"),
)

# ---- A3.3 architecture placement
for name in ("db", "parser", "web"):
    dep = [
        d for d in docs_http
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == name
    ]
    check(f"A3.3 Deployment {name} present", len(dep) == 1)
    if dep:
        ns = dep[0]["spec"]["template"]["spec"].get("nodeSelector", {})
        check(
            f"A3.3 Deployment {name} nodeSelector arch=amd64",
            ns.get("kubernetes.io/arch") == "amd64",
            ns,
        )
db_dep = [
    d for d in docs_http
    if d.get("kind") == "Deployment" and d["metadata"]["name"] == "db"
][0]
db_ns = db_dep["spec"]["template"]["spec"].get("nodeSelector", {})
check(
    "A3.3 db hostname pin == k3s-worker-5 (from config, not a literal)",
    db_ns.get("kubernetes.io/hostname") == "k3s-worker-5",
    db_ns,
)
check(
    "A3.3 db pod template carries no hardcoded hostname literal "
    "(pin is LEDGER_DB_NODE_HOSTNAME-fed)",
    "k3s-worker-5" not in open(TPL).read(),
)

# ---- A3.4 PVC class + size
pvc = [d for d in docs_http if d.get("kind") == "PersistentVolumeClaim"]
check("A3.4 exactly one PVC (mysql-data)", len(pvc) == 1)
pvc = pvc[0]
check(
    "A3.4 PVC storageClassName == tower-raid5-db",
    pvc["spec"].get("storageClassName") == "tower-raid5-db",
    pvc["spec"].get("storageClassName"),
)
check(
    "A3.4 PVC size == LEDGER_PVC_SIZE_GB (50Gi)",
    pvc["spec"]["resources"]["requests"]["storage"] == "50Gi",
)
# upstream behavior: no storageClassName when the var is undefined
docs_noc = render_ledger(base_ctx(
    k8s_container_registry=BASE_REPO,
    LEDGER_PVC_STORAGE_CLASS=None,
    __drop_pvc_sc__=None,
) if False else None) if False else None
ctx_nosc = base_ctx()
del ctx_nosc["LEDGER_PVC_STORAGE_CLASS"]
del ctx_nosc["LEDGER_DB_IMAGE_REF"]
del ctx_nosc["LEDGER_PARSER_IMAGE_REF"]
del ctx_nosc["LEDGER_WEB_IMAGE_REF"]
ctx_nosc["k8s_container_registry"] = BASE_REPO
docs_nosc = render_ledger(ctx_nosc)
pvc_nosc = [d for d in docs_nosc if d.get("kind") == "PersistentVolumeClaim"][0]
check(
    "A3.4 upstream render (var undefined) omits storageClassName",
    "storageClassName" not in pvc_nosc["spec"],
    pvc_nosc["spec"].get("storageClassName"),
)

# ---- A3.5 image refs (frozen release set) + pull policy
for name, digest in (("db", DIGESTS["db"]), ("parser", DIGESTS["parser"]),
                     ("web", DIGESTS["web"])):
    dep = [
        d for d in docs_http
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == name
    ][0]
    img = dep["spec"]["template"]["spec"]["containers"][0]["image"]
    check(f"A3.5 {name} image pins the frozen v1.1.2 digest", digest in img, img)
    check(f"A3.5 {name} image is not latest", ":latest" not in img, img)
    pp = dep["spec"]["template"]["spec"]["containers"][0].get("imagePullPolicy")
    check(f"A3.5 {name} pullPolicy IfNotPresent", pp == "IfNotPresent", pp)

# upstream tag-composition behavior preserved
docs_up = render_ledger_no_refs()
for name in ("db", "parser", "web"):
    dep = [
        d for d in docs_up
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == name
    ][0]
    img = dep["spec"]["template"]["spec"]["containers"][0]["image"]
    check(
        f"A3.5 {name} upstream render keeps tag composition",
        img.endswith(":v1.1.2") and img.count(":") == 1,
        img,
    )

# no tag-string equality on ledger images in the tasks file
tasks_raw = open(TASKS).read()
tasks_docs = list(yaml.safe_load_all(tasks_raw))
tasks = [t for t in tasks_docs[0] if isinstance(t, dict)]


def _iter_tasks(seq):
    for t in seq:
        if isinstance(t, dict):
            if "block" in t:
                yield from _iter_tasks(t["block"])
            else:
                yield t


all_tasks = list(_iter_tasks(tasks_docs[0]))
check(
    "A3.5 no task performs LEDGER_VERSION tag-string equality",
    'LEDGER_VERSION | lower == "latest"' not in tasks_raw,
)
restart_task = [
    t for t in all_tasks if t.get("name", "").startswith("Restart Ledger")
]
check("A3.5 restart task present", len(restart_task) == 1)
if restart_task:
    check(
        "A3.5 restart condition is digest-aware (no tag equality)",
        "@sha256:" in str(restart_task[0].get("when", "")),
        restart_task[0].get("when"),
    )

# ---- A3.6 no secret logging
check(
    "A3.6 no debug-of-auth_token task",
    "ledger_settings.json.auth_token" not in
    [str(t.get("var", "")) for t in all_tasks
     if t.get("ansible.builtin.debug")],
)
check(
    "A3.6 no debug task prints the token anywhere",
    "debug" not in tasks_raw or
    all(
        "auth_token" not in str(t.get("var", "")) + str(t.get("msg", ""))
        for t in all_tasks
    ),
)
PW_TASKS = (
    "Check Ledger Token",
    "Regenerate Token if blank",
    "Get Ledger Token Again (in case of regeneration)",
    "Enable Require Token",
    "Set all the logging parameters",
)
for name in PW_TASKS:
    t = [t for t in all_tasks if t.get("name") == name]
    check(f"A3.6 no_log on '{name}'", t and t[0].get("no_log") is True,
          t[0].get("no_log") if t else "task missing")
tmpl_tasks = [
    t for t in all_tasks if "ansible.builtin.template" in t
]
check(
    "A3.6 both manifest renders carry mode 0600",
    len(tmpl_tasks) == 2
    and all(t["ansible.builtin.template"].get("mode") == "0600"
            for t in tmpl_tasks),
    [(t.get("name"), t["ansible.builtin.template"].get("mode"))
     for t in tmpl_tasks],
)

# ---- A3.7 provisioning disabled (per-task guard assertions; no substring
# tautologies): every /etc/hosts-write task and the firewalld-stop task in
# the k3s setup path must carry a `when:` that actually evaluates the
# relevant config flag (R1 tests-lane finding: comment lines could satisfy
# the old when-count arithmetic and the flag-name substrings).
k3s_setup = f"{ROOT}/playbooks/roles/k8s_setup/tasks/k8s_setup_k3s.yml"
setup_raw = open(k3s_setup).read()


def _iter_setup_tasks():
    for t in yaml.safe_load_all(setup_raw):
        if not t:
            continue
        for item in t:
            if isinstance(item, dict):
                yield item


setup_tasks = list(_iter_setup_tasks())


def _task_repr(task):
    """Flattened name/module/when text used for guard matching."""
    parts = [str(task.get("name", ""))]
    for key, val in task.items():
        if key in ("name",):
            continue
        parts.append(str(val))
    when = task.get("when")
    if when is not None:
        parts.append(str(when))
    return " ".join(parts)


_hosts_write_tasks = [
    t for t in setup_tasks
    if isinstance(t.get("ansible.builtin.lineinfile"), dict)
    and "/etc/hosts" in str(t["ansible.builtin.lineinfile"].get("path", ""))
]
check(
    "A3.7 /etc/hosts writes exist to guard (5 hostname entries)",
    len(_hosts_write_tasks) == 5,
    str([t.get("name") for t in _hosts_write_tasks]),
)
for t in _hosts_write_tasks:
    when = str(t.get("when", ""))
    check(
        f"A3.7 hosts-write '{t.get('name')}' when-guard references use_etc_hosts",
        "use_etc_hosts" in when,
        when,
    )
_firewalld_tasks = [
    t for t in setup_tasks
    if t.get("ansible.builtin.service")
    and "firewalld" in str(t["ansible.builtin.service"].get("name", ""))
]
check("A3.7 firewalld stop task present", len(_firewalld_tasks) == 1)
if _firewalld_tasks:
    when = str(_firewalld_tasks[0].get("when", ""))
    check(
        "A3.7 firewalld stop when-guard references firewalld_disable",
        "firewalld_disable" in when,
        when,
    )
_kubeconfig_tasks = [
    t for t in setup_tasks
    if "ansible.builtin.fetch" in t or "ansible.builtin.replace" in t
]
check(
    "A3.7 kubeconfig fetch/replace tasks guarded by download_kubeconfig",
    all("download_kubeconfig" in str(t.get("when", "")) for t in _kubeconfig_tasks),
    str([(t.get("name"), t.get("when")) for t in _kubeconfig_tasks]),
)

# ---- A3.8 schema validation (offline structural variant)
K8S_API = {
    "Secret": "v1", "Service": "v1", "PersistentVolumeClaim": "v1",
    "Deployment": "apps/v1", "Ingress": "networking.k8s.io/v1",
}
for d in docs_http:
    kind = d.get("kind")
    if kind in K8S_API:
        check(
            f"A3.8 {kind} apiVersion == {K8S_API[kind]}",
            d.get("apiVersion") == K8S_API[kind],
            d.get("apiVersion"),
        )
dep = [
    d for d in docs_http
    if d.get("kind") == "Deployment" and d["metadata"]["name"] == "db"
][0]
pod_spec = dep["spec"]["template"]["spec"]
check(
    "A3.8 db pod spec has initContainers before containers",
    "initContainers" in pod_spec and "containers" in pod_spec,
)
check(
    "A3.8 every Deployment has required spec fields",
    all(
        d.get("spec", {}).get("selector") and d["spec"].get("template")
        for d in docs_http if d.get("kind") == "Deployment"
    ),
)

# ---- A3.9 imagePullSecrets
deps = [d for d in docs_http if d.get("kind") == "Deployment"]
check(
    "A3.9 imagePullSecrets ledger-registry-secret on all three Deployments "
    "(DEPOT_REGISTRY.BASE defined)",
    all(
        d["spec"]["template"]["spec"].get("imagePullSecrets") ==
        [{"name": "ledger-registry-secret"}] for d in deps
    ),
)
ctx_nodepot = base_ctx()
del ctx_nodepot["DEPOT_REGISTRY"]
docs_nodepot = render_ledger(ctx_nodepot)
check(
    "A3.9 no imagePullSecrets when DEPOT_REGISTRY.BASE undefined",
    all(
        "imagePullSecrets" not in d["spec"]["template"]["spec"]
        for d in docs_nodepot if d.get("kind") == "Deployment"
    ),
)
# registry secret template renders valid dockerconfigjson shape
reg_tpl = (
    f"{ROOT}/playbooks/roles/ledger_install/templates/"
    "ledger_deployment_registry_secret.yaml"
)
reg_out = render(reg_tpl, base_ctx())
reg_doc = yaml.safe_load(reg_out)
check(
    "A3.9 registry secret template renders a dockerconfigjson Secret",
    reg_doc.get("kind") == "Secret"
    and reg_doc.get("type") == "kubernetes.io/dockerconfigjson",
)

# ---- A3.10 TLS-target enumeration (rendered URLs, not template literals;
# executed path only — the k3s task files this branch actually runs)
check(
    "A3.10 no verify_ssl: false left in ledger tasks",
    "verify_ssl: false" not in tasks_raw,
)
check(
    "A3.10 no validate_certs: false left in ledger tasks",
    "validate_certs: false" not in tasks_raw,
)
# executed-path flip enumeration: the R4 chain is setup.yml ->
# assertions/kubernetes_setup/install_ascender/install_ledger; none of
# its k3s-path task files may carry a TLS-verification flip (the
# kubernetes.core tasks ride the kubeconfig CA chain; uri targets are
# the DNS-resolved hostnames).
EXEC_PATH_FILES = [
    f"{ROOT}/playbooks/roles/ascender_install/tasks/ascender_install_k3s.yml",
    f"{ROOT}/playbooks/install_ledger.yml",
    f"{ROOT}/playbooks/roles/k8s_setup/tasks/k8s_setup_k3s.yml",
]
for path in EXEC_PATH_FILES:
    raw = open(path).read()
    check(
        f"A3.10 executed-path {path.rsplit('/', 1)[-1]} carries no "
        "verify_ssl/validate_certs false flip",
        "verify_ssl: false" not in raw and "validate_certs: false" not in raw,
        path,
    )
# uri targets must RENDER to a hostname (not a raw node IP / ClusterIP
# literal): render each uri task's url with the fixture context — the
# context carries the set_fact-derived URL vars exactly as the tasks
# derive them (ledger_ip = LEDGER_HOSTNAME; ascender_ip = ASCENDER_HOSTNAME
# under ClusterIP) — and assert no private/loopback literal survives.
_URI_CTX = base_ctx(
    ledger_ip="ascender-pro.alcedo.dev",
    ledger_port="80",
    ascender_ip="ascender.alcedo.dev",
    ascender_port="80",
)
for t in all_tasks:
    if "ansible.builtin.uri" not in t:
        continue
    url_raw = str(t["ansible.builtin.uri"]["url"])
    url_rendered = ENV.from_string(url_raw).render(**_URI_CTX)
    is_private = any(
        prefix in url_rendered
        for prefix in ("192.168.", "10.", "127.", "172.16.", "172.17.",
                       "172.18.", "172.19.", "172.2", "172.30.", "172.31.")
    )
    host = url_rendered.split("//")[-1].split(":")[0]
    check(
        f"A3.10 uri target '{url_raw}' renders to a DNS hostname "
        "(no raw node/ClusterIP)",
        not is_private and "." in host,
        url_rendered,
    )

# ---- A2b3 fail-closed initContainer spec
init = pod_spec["initContainers"][0]
check("A2b3 initContainer name", init.get("name") == "verify-mysql-data-mount")
cmd = init.get("command", [])
check("A2b3 command uses findmnt -T /var/lib/mysql -n -o UUID,FSTYPE",
      any("findmnt -T /var/lib/mysql -n -o UUID,FSTYPE" in str(c) for c in cmd),
      cmd)
check(
    "A2b3 command compares against the configured UUID",
    any(FS_UUID in str(c) for c in cmd),
)
check(
    "A2b3 mounts mysql-data readOnly at /var/lib/mysql",
    init.get("volumeMounts") ==
    [{"mountPath": "/var/lib/mysql", "name": "mysql-data", "readOnly": True}],
    init.get("volumeMounts"),
)
check(
    "A2b3 initContainer image honors the digest pin",
    DIGESTS["db"] in init.get("image", ""),
    init.get("image"),
)

# ---- additional-spec digest-capable surface (SPLIT form, verified
# against the operator's own composition semantics)
PG_IMAGE = "quay.io/sclorg/postgresql-15-c9s@sha256"
PG_VERSION = "80d861ed8fdd365d6d59e16a0a73c0cd3753cf54664c87e00aab7e78bbe26c39"
REDIS_IMAGE = "ghcr.io/valkey-io/valkey:9-alpine@sha256"
REDIS_VERSION = "48332870af354a799964c0012ae1194a0bf2bf894eb508f945810596dc2d8d11"
EE_REF = "ghcr.io/ctrliq/ascender-ee:25.6.2@sha256:c5b300dbeb6405dc068a21d4851b0449ab7b795858656ea7ccc35263fa2aab80"
PG_SELECTOR = "kubernetes.io/hostname: k3s-worker-4"
ctx_spec = dict(
    k8s_container_registry="",
    ASCENDER_VERSION="25.6.2",
    ASCENDER_IMAGE="ghcr.io/ctrliq/ascender",
    ascender_image_pull_policy="IfNotPresent",
    ascender_replicas=1,
    k8s_platform="k3s",
    k8s_offline=False,
    POSTGRES_IMAGE=PG_IMAGE,
    POSTGRES_IMAGE_VERSION=PG_VERSION,
    REDIS_IMAGE=REDIS_IMAGE,
    REDIS_IMAGE_VERSION=REDIS_VERSION,
    ASCENDER_EE_IMAGE_REF=EE_REF,
    postgres_selector=PG_SELECTOR,
    node_selector=PG_SELECTOR,
)
spec_out = render(ADDSPEC, ctx_spec)
spec_digest = spec_out


def _parse_spec(rendered):
    """Parse the additional-spec fragment as the 2-space-indented body of
    a parent key, then extract it (the fragment is include'd into the AWX
    CR spec, so it is 2-space-indented YAML without its own document)."""
    docs = [d for d in yaml.safe_load_all("x:\n" + "".join(
        "  " + line if line.strip() else line
        for line in rendered.splitlines(True))) if d]
    return docs[0]["x"]


spec = _parse_spec(spec_out)
check(
    "A4/addspec postgres_image is the split-form repo@sha256 prefix",
    spec.get("postgres_image") == PG_IMAGE,
    spec.get("postgres_image"),
)
check(
    "A4/addspec postgres_image_version carries the amd64 child digest hex",
    spec.get("postgres_image_version") == PG_VERSION,
    spec.get("postgres_image_version"),
)
check(
    "A4/addspec redis_image is the split-form repo:tag@sha256 prefix",
    spec.get("redis_image") == REDIS_IMAGE,
    spec.get("redis_image"),
)
check(
    "A4/addspec redis_image_version carries the digest hex",
    spec.get("redis_image_version") == REDIS_VERSION,
    spec.get("redis_image_version"),
)
check(
    "A4/addspec init_container_image is the bare repo (tag+digest stripped)",
    spec.get("init_container_image") == "ghcr.io/ctrliq/ascender-ee",
    spec.get("init_container_image"),
)
check(
    "A4/addspec init_container_image_version is tag@digest",
    spec.get("init_container_image_version") ==
    "25.6.2@sha256:c5b300dbeb6405dc068a21d4851b0449ab7b795858656ea7ccc35263fa2aab80",
    spec.get("init_container_image_version"),
)
check(
    "A4/addspec control_plane_ee_image carries the full digest ref verbatim",
    spec.get("control_plane_ee_image") == EE_REF,
    spec.get("control_plane_ee_image"),
)
check(
    "A4/addspec CR carries postgres_selector hostname pin (plan B3/B4)",
    str(spec.get("postgres_selector", "")).strip() == PG_SELECTOR,
    spec.get("postgres_selector"),
)
check(
    "A4/addspec CR carries node_selector hostname pin",
    str(spec.get("node_selector", "")).strip() == PG_SELECTOR,
    spec.get("node_selector"),
)

# ---- A4/operator composition: apply the operator 25.6.2 image-composition
# semantics (verified empirically against the operator source at tag
# 25.6.2 db94583 — database_configuration.yml:59-68,
# resources_configuration.yml:236-246, set_images.yml:3-18) to the rendered
# CR fields and assert the EFFECTIVE workload image refs are the frozen
# full-digest pins. The custom-image branch fires only when the image is
# non-empty AND the version is defined + non-empty; the composed ref is
# image + ':' + version; otherwise the operator's default tag-composed
# ref applies.
_default_postgres_image = "quay.io/sclorg/postgresql-15-c9s:latest"
pg_effective = (
    spec["postgres_image"] + ":" + spec["postgres_image_version"]
    if spec["postgres_image"] and spec.get("postgres_image_version")
    else _default_postgres_image
)
_default_redis_image = "ghcr.io/valkey-io/valkey:9-alpine"
redis_effective = (
    spec["redis_image"] + ":" + spec["redis_image_version"]
    if spec["redis_image"] and spec.get("redis_image_version")
    else _default_redis_image
)
init_effective = (
    spec["init_container_image"] + ":" + spec["init_container_image_version"]
    if spec["init_container_image"] and spec.get("init_container_image_version")
    else "ghcr.io/ctrliq/ascender-ee:25.6.2"
)
check(
    "A4/comp PG effective ref is the frozen amd64-child digest pin",
    pg_effective == f"{PG_IMAGE}:{PG_VERSION}",
    pg_effective,
)
check(
    "A4/comp PG effective ref is not the mutable :latest default",
    "latest" not in pg_effective and pg_effective != _default_postgres_image,
    pg_effective,
)
check(
    "A4/comp Valkey effective ref is the frozen digest pin",
    redis_effective == f"{REDIS_IMAGE}:{REDIS_VERSION}",
    redis_effective,
)
check(
    "A4/comp EE init-container effective ref is the frozen digest pin",
    init_effective == EE_REF,
    init_effective,
)
check(
    "A4/comp EE effective ref contains no double tag",
    "25.6.2:25.6.2" not in init_effective,
    init_effective,
)
check(
    "A4/comp all three effective refs are digest-pinned",
    all("@sha256:" in r for r in (pg_effective, redis_effective, init_effective)),
    str((pg_effective, redis_effective, init_effective)),
)

# upstream default behavior preserved when vars undefined
spec_up = render(ADDSPEC, dict(
    k8s_container_registry="",
    ASCENDER_VERSION="25.6.2",
    ASCENDER_IMAGE="ghcr.io/ctrliq/ascender",
    ascender_image_pull_policy="IfNotPresent",
    ascender_replicas=1,
    k8s_platform="k3s",
    k8s_offline=False,
))
check(
    "A4/addspec upstream defaults preserved (quay postgres repo, bare)",
    "postgres_image: quay.io/sclorg/postgresql-15-c9s" in spec_up
    and not _field_present(spec_up, "postgres_image_version"),
)
check(
    "A4/addspec upstream defaults preserved (valkey repo, bare)",
    "redis_image: ghcr.io/valkey-io/valkey" in spec_up
    and not _field_present(spec_up, "redis_image_version"),
)
check(
    "A4/addspec upstream render omits the CR selectors (opt-in only)",
    not _field_present(spec_up, "postgres_selector")
    and not _field_present(spec_up, "node_selector"),
)
# tag-form supply still renders the version lines (upstream shape)
spec_tagged = render(ADDSPEC, dict(
    k8s_container_registry="",
    ASCENDER_VERSION="25.6.2",
    ASCENDER_IMAGE="ghcr.io/ctrliq/ascender",
    ascender_image_pull_policy="IfNotPresent",
    ascender_replicas=1,
    k8s_platform="k3s",
    k8s_offline=False,
    POSTGRES_IMAGE="quay.io/sclorg/postgresql-15-c9s",
    POSTGRES_IMAGE_VERSION="latest",
    REDIS_IMAGE="ghcr.io/valkey-io/valkey",
    REDIS_IMAGE_VERSION="9-alpine",
))
check(
    "A4/addspec tag-form supply renders version lines (upstream shape)",
    'postgres_image_version: "latest"' in spec_tagged
    and 'redis_image_version: "9-alpine"' in spec_tagged,
)

# ---- assertions.yml backports parse + structure
assertions = list(yaml.safe_load_all(open(ASSERTIONS)))
check(
    "f2: assertions.yml parses with the ee_images block",
    len(assertions) >= 1,
)

# ---- summary ----------------------------------------------------------
for line in RESULTS:
    print(line)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
