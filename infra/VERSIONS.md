# Pinned versions

Checked 2026-11-12 via web search of official release pages. Values live in `versions.env`.
Image digests are not resolved yet: see `digests.txt` (TODO markers). Re-check every row before a production build.

| Component | Version | Source | License | Date checked | Notes |
| --- | --- | --- | --- | --- | --- |
| Keycloak | 26.8.2 (released 2026-11-05) | https://www.keycloak.org/downloads , https://github.com/keycloak/keycloak/releases | Apache-2.0 | 2026-11-12 | Image `quay.io/keycloak/keycloak`. One secondary source said 26.8.1; GitHub releases page and endoflife.date say 26.8.2. |
| Apache Guacamole | 1.6.0 (released 2025-06-22) | https://guacamole.apache.org/releases/ | Apache-2.0 | 2026-11-12 | Images `guacamole/guacamole` and `guacamole/guacd`, same tag. No newer stable found. |
| PostgreSQL | 17.11 | https://www.postgresql.org/support/versioning/ | PostgreSQL License | 2026-11-12 | 18.6 is the newest major but 17 (supported to 2029-11) is pinned: Debian 13 ships postgresql-client-17 so pg_dump on the backup host matches the server major. The quarterly minor release was scheduled for 2026-11-12 (today); check for 17.12 and bump. Move to 18 later together with the client package. |
| Caddy | 2.11.9 (released 2026-11-05) | https://github.com/caddyserver/caddy/releases | Apache-2.0 | 2026-11-12 | Image `caddy`. Some trackers still show 2.11.4-2.11.7 (stale). |
| Wazuh | 4.14.10 (released 2026-11-05) | https://documentation.wazuh.com/current/release-notes/release-4-14-10.html , https://github.com/wazuh/wazuh-docker/releases | GPL-2.0 (agent/manager), mixed for indexer/dashboard | 2026-11-12 | 5.0.0 is still release-candidate (rc2 2026-10-30), so 4.14.x is pinned. Server stack comes from the official wazuh-docker single-node deployment at tag v4.14.10. |
| Gitea | 28.3.0 (blog dated 2026-11-01) | https://blog.gitea.com/ | MIT | 2026-11-12 | Version scheme dropped the "1." prefix (1.27.x -> 28.x). Docker tag format and existence of `gitea/gitea:28.3.0` NOT verified on Docker Hub: verify before use. Optional profile only. |
| restic | 0.19.1 (released 2026-07-05) | https://github.com/restic/restic/releases/tag/v0.19.1 | BSD-2-Clause | 2026-11-12 | Binary download; put the SHA256 from the release `SHA256SUMS` in the vault/group_vars (`restic_sha256`). |
| Node (build stage) | 22-bookworm-slim | https://hub.docker.com/_/node | MIT | not re-checked | Dockerfile base only; major tag, digest TODO. |
| Python (runtime) | 3.13-slim-bookworm | https://hub.docker.com/_/python | PSF | not re-checked | Matches `requires-python >=3.13`. |
| uv | 0.11.18 | https://github.com/astral-sh/uv/releases | MIT / Apache-2.0 | local `uv --version` 2026-11-12 | Copied into build stage only. |

## Not yet done

- Digest resolution, SBOM generation (`docker buildx build --sbom=true` or syft), advisory review per component.
- Signature/checksum verification of the Wazuh apt key and restic binary (checksums are required variables in Ansible and the playbooks refuse to run with TODO values).
