# Wazuh (profile: security plane)

Do not reinvent this. Use the official single-node deployment from `wazuh/wazuh-docker`
at the tag matching `WAZUH_VERSION` in `../../versions.env` (currently v4.14.10):

```sh
git clone --branch v4.14.10 --depth 1 https://github.com/wazuh/wazuh-docker.git
cd wazuh-docker/single-node
docker compose -f generate-indexer-certs.yml run --rm generator
# change the default admin / API / dashboard passwords BEFORE first start (their docs list them)
docker compose up -d
```

Notes for this repo:

- Wazuh sits in the management/security zone, not on the employee network. The dashboard is only
  reachable from the management network.
- Agents on workspace VMs enroll against the manager on 1514/tcp and 1515/tcp (see the ansible
  role `wazuh_agent` and the `network_zones` flows).
- Sizing reference from PLAN section 6: 4 vCPU, 8 GiB RAM, 50 GB for 1-25 agents.
- The official compose pulls `wazuh/*` images by tag; pin digests the same way as `../../digests.txt`.
- Not tested in this repository: no Docker on the authoring machine.
