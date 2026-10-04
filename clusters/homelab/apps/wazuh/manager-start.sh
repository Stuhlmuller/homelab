#!/usr/bin/with-contenv bash
# shellcheck shell=bash
# Replace upstream 2-manager, which ignores failing /entrypoint-scripts hooks.
# 0-wazuh-init has restored PVC data; only this script starts Wazuh daemons.
# Any error exits before wazuh-control start, leaving API/agent listeners down.
set -euo pipefail
umask 077
install -m 0600 /run/wazuh/credentials/filebeat.yml /etc/filebeat/filebeat.yml
install -m 0640 -o root -g wazuh /run/wazuh/config/api.yaml /var/ossec/api/configuration/api.yaml
install -m 0640 -o root -g wazuh /run/wazuh/credentials/agent-enrollment-password /var/ossec/etc/authd.pass
install -m 0600 /run/wazuh/credentials/api-admin.json /var/ossec/api/configuration/admin.json
/var/ossec/framework/python/bin/python3 /var/ossec/framework/scripts/create_user.py
rm -f /var/ossec/api/configuration/admin.json
printf '%s\n' admin | /var/ossec/bin/wazuh-keystore -f indexer -k username
/var/ossec/bin/wazuh-keystore -f indexer -k password </run/wazuh/credentials/indexer-admin-password
# Single indexer: a replica cannot be allocated. Preserve upstream mappings.
/var/ossec/framework/python/bin/python3 - <<'PY'
import json
from pathlib import Path
path = Path('/etc/filebeat/wazuh-template.json')
template = json.loads(path.read_text())
template.setdefault('settings', {})['index.number_of_replicas'] = 0
template['settings']['index.number_of_shards'] = 1
template['settings']['index.auto_expand_replicas'] = 'false'
path.write_text(json.dumps(template))
PY
/var/ossec/bin/wazuh-analysisd -t
/var/ossec/bin/wazuh-logcollector -t
/usr/share/filebeat/bin/filebeat test config -c /etc/filebeat/filebeat.yml -path.home /usr/share/filebeat
/var/ossec/bin/wazuh-control start
