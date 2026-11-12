"""Offline checks for infra/ and policies/. No Docker or Ansible needed.

    uv run --with pyyaml --with jinja2 python infra/tests/validate.py

Checks: YAML/JSON parse, Jinja syntax, em dash ban, no floating tags, policy vs Guacamole
templates, Keycloak realm invariants, compose network wiring, rendered nftables rules, shell syntax.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
errors: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def files(base: Path, *patterns: str):
    for pat in patterns:
        yield from (p for p in base.rglob(pat) if p.is_file() and "collections" not in p.parts)


# ---- parse everything ---------------------------------------------------------------
for p in [*files(INFRA, "*.yml", "*.yaml"), *files(ROOT / "policies", "*.yaml")]:
    try:
        yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        errors.append(f"yaml {p.relative_to(ROOT)}: {e}")
for p in files(INFRA, "*.json"):
    try:
        json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        errors.append(f"json {p.relative_to(ROOT)}: {e}")
env = jinja2.Environment(extensions=[])
for p in files(INFRA, "*.j2"):
    try:
        env.parse(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        errors.append(f"jinja {p.relative_to(ROOT)}: {e}")

# ---- text hygiene ---------------------------------------------------------------------
scan = [*INFRA.rglob("*"), *(ROOT / "policies").rglob("*"), ROOT / "Dockerfile", ROOT / ".dockerignore"]
for p in scan:
    if not p.is_file():
        continue
    raw = p.read_bytes()
    text = raw.decode("utf-8", "replace")
    rel = p.relative_to(ROOT)
    check(chr(0x2014) not in text, f"em dash in {rel}")
    check(b"\r\n" not in raw, f"CRLF line endings in {rel}")
    if p.suffix in {".yml", ".yaml", ".j2", ".sh", ".md"} or p.name in {"Dockerfile", "Caddyfile"}:
        check(not re.search(r"(?im)^\s*image:\s*\S+:latest\b", text), f"floating latest tag in {rel}")
        check(not re.search(r"(?im)^FROM\s+\S+:latest\b", text), f"floating latest tag in {rel}")

# ---- policy <-> guacamole templates --------------------------------------------------------
pol = yaml.safe_load((ROOT / "policies/guacamole-transfer-policy.yaml").read_text(encoding="utf-8"))
for name, prof in pol["profiles"].items():
    tpl = json.loads((ROOT / prof["template"]).read_text(encoding="utf-8"))
    params = tpl["parameters"]
    for k, v in {**pol["invariants"], **prof["params"]}.items():
        check(params.get(k) == v, f"{prof['template']}: {k} is {params.get(k)!r}, policy says {v!r}")
    check("recording-path" not in params, f"{prof['template']}: recordings are out of scope")
    check("password" not in params and "username" not in params, f"{prof['template']}: no stored credentials")

# ---- keycloak realm ----------------------------------------------------------------------------
realm = json.loads((INFRA / "keycloak/realm-tracking.json").read_text(encoding="utf-8"))
roles = {r["name"] for r in realm["roles"]["realm"]}
check(roles == {"employee", "manager", "it", "security", "approver", "admin"}, f"realm roles: {roles}")
check(realm["bruteForceProtected"] is True, "brute force protection off")
check(realm["accessTokenLifespan"] <= 300, "access token lifespan too long")
check(realm["sslRequired"] == "all", "sslRequired must be all")
# No custom flows: a non-null authenticationFlows makes Keycloak import only that list and skip the
# built-in flows and bindings. OTP comes from the default browser flow plus the CONFIGURE_TOTP default action.
check("authenticationFlows" not in realm and "browserFlow" not in realm, "realm must not define authenticationFlows/browserFlow (breaks the built-in flows)")
check(any(a["alias"] == "CONFIGURE_TOTP" and a["defaultAction"] for a in realm["requiredActions"]), "CONFIGURE_TOTP not default")
clients = {c["clientId"]: c for c in realm["clients"]}
portal = clients["portal"]
check(clients["admin-cli"]["directAccessGrantsEnabled"] is False, "admin-cli password grant must be off")
check(all(c.get("directAccessGrantsEnabled") is False for c in realm["clients"] if c["protocol"] == "openid-connect"), "no client may allow the password grant")
check(portal["publicClient"] is False, "portal client must be confidential")
check(portal["implicitFlowEnabled"] is False and portal["directAccessGrantsEnabled"] is False, "portal grants too wide")
check(portal["attributes"]["pkce.code.challenge.method"] == "S256", "PKCE S256 missing")
for c in (c for c in realm["clients"] if c.get("standardFlowEnabled", True)):
    check(bool(c.get("redirectUris")) and all("*" not in u for u in c["redirectUris"]), f"client {c['clientId']}: redirect URIs must be exact")
check(portal["secret"] == "${PORTAL_CLIENT_SECRET}", "portal secret must come from the environment")
check(any(c["protocol"] == "saml" for c in realm["clients"]), "guacamole SAML client missing")

# ---- compose wiring ----------------------------------------------------------------------------
dc = yaml.safe_load((INFRA / "compose/docker-compose.lab.yml").read_text(encoding="utf-8"))
nets, svcs = dc["networks"], dc["services"]
for name in ("edge", "app", "gateway", "data"):
    check(name in nets, f"compose: network {name} missing")
for n in ("app", "gateway", "data"):
    check(nets[n].get("internal") is True, f"compose: network {n} must be internal")


def netlist(s):
    n = svcs[s].get("networks", [])
    return set(n if isinstance(n, list) else n.keys())


check(netlist("guacd") == {"gateway", "workspace"}, f"guacd networks: {netlist('guacd')}")
check([s for s in svcs if "workspace" in netlist(s) and s != "guacd"] == [], "only guacd may be on workspace")
check([s for s in svcs if "gateway" in netlist(s)] == ["guacd", "guacamole"], "gateway net: only guacd + guacamole")
check("edge" in netlist("caddy") and [s for s in svcs if "edge" in netlist(s)] == ["caddy"], "only caddy on edge")
check("ports" not in svcs["postgres"] and "ports" not in svcs["guacd"], "postgres/guacd must not publish ports")
for s, d in svcs.items():
    if "image" in d:
        img = d["image"]
        check(":" in img and not img.endswith(":latest"), f"compose {s}: image not pinned: {img}")
    for dep in (d.get("depends_on") or {}):
        check(dep in svcs, f"compose {s}: depends_on unknown {dep}")
    for n in netlist(s) if "networks" in d else []:
        check(n in nets, f"compose {s}: unknown network {n}")
# portal runs unprivileged: it may only mount the exported root.crt volume, never caddy's root-only storage
for s in ("portal-api", "portal-worker"):
    vols = [str(x) for x in svcs[s].get("volumes", [])]
    check(not any(x.startswith("caddy_data") for x in vols), f"compose {s}: must not mount caddy_data")
    check(svcs[s]["environment"]["SSL_CERT_FILE"].startswith("/lab-ca/") and any(x.startswith("lab_ca:/lab-ca") for x in vols), f"compose {s}: SSL_CERT_FILE must come from the lab_ca volume")
check("caddy-ca-export" in svcs["portal-api"]["depends_on"], "portal-api must wait for caddy-ca-export")
for var in re.findall(r"\$\{(\w+_VERSION)", (INFRA / "compose/docker-compose.lab.yml").read_text(encoding="utf-8")):
    check(re.search(rf"^{var}=\d", (INFRA / "versions.env").read_text(encoding="utf-8"), re.M) is not None, f"{var} not in versions.env")
envex = (INFRA / "compose/.env.example").read_text(encoding="utf-8")
for line in envex.splitlines():
    if re.match(r".*(PASSWORD|SECRET)=", line):
        check(line.endswith("=CHANGE_ME"), f".env.example secret not a placeholder: {line}")

# ---- render the firewall for a workspace host and a docker host ----------------------------
all_vars = yaml.safe_load((INFRA / "ansible/group_vars/all.yml").read_text(encoding="utf-8"))
# resolve the few {{ }} references inside the flow list by hand (no ansible here)
simple = {k: v for k, v in all_vars.items() if isinstance(v, (str, int, list)) and not str(v).startswith("{{")}
ctx = {**simple, "nz_zones": all_vars["nz_zones"], "ansible_managed": "managed"}


def resolve(v):
    if isinstance(v, str) and v.startswith("{{"):
        return jinja2.Template(v).render(**ctx)
    return v


flows = []
for f in all_vars["nz_flows"]:
    g = dict(f)
    for key in ("sources", "destinations"):
        if key in g:
            raw = g[key]
            g[key] = ctx["nz_guacd_hosts"] if isinstance(raw, str) else [resolve(x) for x in raw]
    flows.append(g)
tpl = jinja2.Environment(trim_blocks=True, lstrip_blocks=False).from_string(
    (INFRA / "ansible/roles/network_zones/templates/portal-zones.nft.j2").read_text(encoding="utf-8")
)
zone_defaults = yaml.safe_load((INFRA / "ansible/roles/network_zones/defaults/main.yml").read_text(encoding="utf-8"))
base = {**{k: v for k, v in zone_defaults.items() if k != "nz_docker_host"}, **ctx, "nz_flows": flows, "nz_ssh_port": 22, "nz_output_drop_zones": ["workspace"]}
ws = tpl.render(**base, nz_zone="workspace", nz_docker_host=False)
check("policy drop" in ws.split("chain output")[1], "workspace output must default drop")
check("guacd-to-workspace-rdp" in ws and "tcp dport { 3389 }" in ws, "workspace must accept rdp")
check("ip saddr { 10.20.30.10 }" in ws.split("guacd-to-workspace-rdp")[0].splitlines()[-1], "rdp only from guacd")
check(ws.count("3389") == 1, "3389 appears more than once for workspace")
check(all(f"ip saddr {{ {z} }}" not in ws for z in (all_vars["nz_zones"]["workspace"], all_vars["nz_zones"]["data"])), "workspace accepts peers/data")
gw = tpl.render(**base, nz_zone="gateway", nz_docker_host=True)
check("chain pre_dnat" in gw and "jump inbound" in gw, "docker host must filter before DNAT")
# guacd's docker bridge may only forward RDP to the workspace zone
check("chain guacd_egress" in gw, "gateway host needs the guacd_egress forward chain")
egress = gw.split("chain guacd_egress")[1].split("}")[0]
check(f'iifname "{all_vars.get("nz_guacd_bridge", zone_defaults["nz_guacd_bridge"])}" drop' in egress, "guacd bridge must default drop")
check(f"ip daddr {all_vars['nz_zones']['workspace']} tcp dport 3389 accept" in egress, "guacd bridge may only reach workspace:3389")
check(f"com.docker.network.bridge.name: {{{{ nz_guacd_bridge }}}}" in (INFRA / "ansible/roles/guacamole_host/templates/docker-compose.yml.j2").read_text(encoding="utf-8"), "guacd rdp network must use the fixed bridge name")
check("chain guacd_egress" not in ws, "guacd egress chain only belongs on the gateway")
# backups: data01 pushes to the restic repository on backup01 over ssh, so mgmt must accept exactly that
backup_hosts = all_vars["data_host"], all_vars["nz_backup_host"]
mg = tpl.render(**base, nz_zone="mgmt", nz_docker_host=False)
check(f"ip saddr {{ {backup_hosts[0]} }} ip daddr {{ {backup_hosts[1]} }} tcp dport {{ 22 }} accept" in mg, "mgmt does not accept data host -> backup01 ssh (backup-to-repo)")
inv = yaml.safe_load((INFRA / "ansible/inventory.example.yml").read_text(encoding="utf-8"))["all"]["children"]
check(list(inv["backup_sources"]["hosts"]) == ["data01"] and inv["zone_data"]["hosts"]["data01"]["ansible_host"] == all_vars["data_host"], "backup source is not the data host")
check(inv["zone_mgmt"]["hosts"]["backup01"]["ansible_host"] == all_vars["nz_backup_host"], "backup01 address != nz_backup_host")
check("restic-sftp" in all_vars["common_ssh_extra_groups"], "sshd on backup01 must allow the restic-sftp group")
if shutil.which("nft"):
    # nft -c still needs CAP_NET_ADMIN; CI runners are non-root with passwordless sudo.
    nft = ["sudo", "-n", "nft"] if os.name != "nt" and os.geteuid() != 0 and shutil.which("sudo") else ["nft"]
    for name, text in (("workspace", ws), ("gateway", gw), ("mgmt", mg)):
        with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as t:
            t.write(text)
        r = subprocess.run([*nft, "-c", "-f", t.name], capture_output=True, text=True)
        check(r.returncode == 0, f"nft -c {name}: {r.stderr}")
else:
    print("note: nft not installed, rendered ruleset not syntax-checked")

# ---- shell scripts ---------------------------------------------------------------------------------
bash = shutil.which("bash")
for p in [*files(INFRA, "*.sh"), *files(INFRA, "*.sh.j2")]:
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".j2":
        text = jinja2.Environment(trim_blocks=True, undefined=jinja2.DebugUndefined).from_string(text).render(
            ansible_managed="m", backup_conf_dir="/etc/x", backup_staging_dir="/var/x", backup_databases=["a"],
            backup_db_host="h", backup_db_port=5432, backup_db_user="u", inventory_hostname="h",
            backup_keycloak_export_cmd="", backup_gitea_container="", backup_restore_test_scratch_db_url="")
    check("set -euo pipefail" in text or "set -eu" in text, f"{p.name}: missing strict mode")
    if bash:
        r = subprocess.run([bash, "-n"], input=text, capture_output=True, text=True)
        check(r.returncode == 0, f"bash -n {p.name}: {r.stderr}")

# ---- ansible role invariants (static: ansible itself is not run here) ----------------------------
roles = INFRA / "ansible/roles"
bk = (roles / "backup/tasks/main.yml").read_text(encoding="utf-8")
for needle in ("id_ed25519", "known_hosts", "StrictHostKeyChecking yes", "BatchMode yes"):
    check(needle in bk, f"backup role: sftp repository auth needs {needle}")
# YAML folds a line break inside a double-quoted scalar into a space; the key file must end in a real newline.
ssh_task = next(t for t in yaml.safe_load(bk) if str(t.get("name", "")).startswith("SSH identity"))
check(ssh_task["ansible.builtin.copy"]["content"].endswith(chr(10)), "backup role: id_ed25519 content must end with a newline (ssh rejects a key without one)")
ph = (roles / "portal_host/templates/docker-compose.yml.j2").read_text(encoding="utf-8")
check("portal_migrator_database_url" not in ph, "portal_host: the owner-role URL must not be rendered into docker-compose.yml")
lab = yaml.safe_load((INFRA / "compose/docker-compose.lab.yml").read_text(encoding="utf-8"))
check(str(lab["services"]["guac-schema"].get("user")) == "0", "guac-schema must run as root to write the fresh root-owned volume")
common = (roles / "common/tasks/main.yml").read_text(encoding="utf-8")
check("common_apt_mirror" in common and "debian.sources" in common, "common role must point mirror-only hosts at the internal mirror")
check(all_vars["common_apt_mirror"] == "{{ internal_mirror_url if nz_zone in nz_output_drop_zones else '' }}", "apt mirror must be used exactly on egress-dropped zones")
wz = (roles / "wazuh_agent/tasks/main.yml").read_text(encoding="utf-8")
check("get_url" not in wz and "packages.wazuh.com" not in (roles / "wazuh_agent/tasks/main.yml").read_text(encoding="utf-8"), "wazuh agent must not download from the internet")
gh = (roles / "guacamole_host/tasks/main.yml").read_text(encoding="utf-8")
check("guacamole-bootstrap.sql" in gh and "guacadmin must be disabled" in gh and "guacamole_bootstrap_admin" in gh, "guacamole_host must run the bootstrap SQL and assert guacadmin is disabled")
wv = (roles / "workspace_vm/tasks/main.yml").read_text(encoding="utf-8")
check("SHA256:" in wv and "tr A-F a-f" not in wv, "xrdp fingerprint must be emitted as SHA256:AB:CD:... (uppercase)")

prov = INFRA / "guacamole/provision-connection.sh"
if bash:
    good = "SHA256:" + ":".join(["AB"] * 32)
    cases = {"hex-no-colons": "ab" * 32, "short": "SHA256:AB:CD", "not-hex": "SHA256:" + ":".join(["ZZ"] * 32), good: good, "lowercase": good.lower()}
    for label, fp in cases.items():
        r = subprocess.run([bash, str(prov), str(INFRA / "guacamole/connection-template.json"), "a@b.test", "h", fp],
                           capture_output=True, text=True, env={"PATH": __import__("os").environ["PATH"]})
        rejected = "fingerprint must look like" in r.stderr
        check(rejected == (label in {"hex-no-colons", "short", "not-hex"}), f"provision-connection.sh fingerprint check wrong for {label}: {r.stderr.strip()}")
ptxt = prov.read_text(encoding="utf-8")
check(ptxt.index("/users/${uenc}\"") < ptxt.index('-X POST --data @- "${base}/connections"'), "provision: user must exist before the connection is created")
check("trap" in ptxt and "-X DELETE" in ptxt, "provision: failed grant must delete the new connection")

if errors:
    print("FAIL")
    print("\n".join(f" - {e}" for e in errors))
    sys.exit(1)
print("OK: infra and policies validated")
