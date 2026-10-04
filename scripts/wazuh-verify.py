#!/usr/bin/env python3
"""Read-only live log-ingestion proof; print counts, never credentials or log bodies."""
import subprocess
import sys

QUERY = r'''
import base64,json,ssl,urllib.request
from pathlib import Path
password=Path('/run/wazuh/credentials/indexer-admin-password').read_text().strip()
context=ssl.create_default_context(cafile='/run/wazuh/tls/ca.crt')
authorization='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
def count(index,filters):
    request=urllib.request.Request('https://wazuh-indexer.wazuh.svc.cluster.local:9200/'+index+'/_count',
        data=json.dumps({'query':{'bool':{'filter':filters}}}).encode(),
        headers={'Authorization':authorization,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(request,context=context,timeout=20) as response:
        return json.load(response)['count']
checks=[]
for source,age in [('kubernetes.container','15m'),('kubernetes.audit','15m'),('kubernetes.event','24h'),('talos','24h')]:
    checks.append((source,count('wazuh-archives-*',[{'range':{'timestamp':{'gte':'now-'+age}}},
        {'match_phrase':{'data.homelab_source':source}}])))
for node in ['acer','zimaboard-0','zimaboard-1','zimaboard-2']:
    checks.append(('container:'+node,count('wazuh-archives-*',[
        {'range':{'timestamp':{'gte':'now-15m'}}},{'match_phrase':{'data.kubernetes.host':node}}])))
for address in ['10.1.0.199','10.1.0.200','10.1.0.201','10.1.0.202']:
    checks.append(('talos:'+address,count('wazuh-archives-*',[
        {'range':{'timestamp':{'gte':'now-24h'}}},{'match_phrase':{'data.homelab_source':'talos'}},
        {'wildcard':{'data.source_address':address+'*'}}])))
for index in ['wazuh-archives-*','wazuh-alerts-*']:
    checks.append(('canary:'+index,count(index,[{'range':{'timestamp':{'gte':'now-15m'}}},
        {'match_phrase':{'data.kubernetes.container_name':'canary'}},
        {'wildcard':{'data.log':'*homelab_siem_canary*'}}])))
for name,value in checks:
    print(name+': '+str(value)+' recent records')
if any(value==0 for _,value in checks):
    raise SystemExit('Incomplete source/canary coverage; inspect private diagnostics')
print('Cluster source and canary checks passed; external device coverage requires separate evidence.')
'''


def main():
    result = subprocess.run([
        "kubectl", "--request-timeout=30s", "-n", "wazuh", "exec",
        "statefulset/wazuh-manager", "-c", "manager", "--",
        "/var/ossec/framework/python/bin/python3", "-I", "-c", QUERY],
        text=True, capture_output=True, timeout=240)
    if result.returncode:
        # API failure bodies and Python errors can contain authentication context.
        # Only count lines from our own fixed-format reporter leave the process.
        for line in result.stdout.splitlines():
            if line.endswith(" recent records"):
                print(line)
        raise SystemExit("Wazuh ingestion verification failed; credentials and raw diagnostics withheld")
    print(result.stdout, end="")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.SubprocessError, OSError):
        print("Wazuh read-only verification could not finish", file=sys.stderr)
        raise SystemExit(1) from None
