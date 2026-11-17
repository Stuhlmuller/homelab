#!/usr/bin/env python3
"""Exercise actual Kubernetes provider requests against an isolated loopback API.

The fixture supplies discovery/schema/CRUD and a deliberate SSA conflict response;
it does not reimplement provider planning. This proves the real provider preserves
refreshed values, sends non-forced requests, and propagates conflicts. It is not a
substitute for live Kubernetes managed-fields or registry/controller acceptance.
"""
import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import Thread
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
GROUPS = {'argoproj.io': ('Application', 'applications'),
          'argocd-image-updater.argoproj.io': ('ImageUpdater', 'imageupdaters')}
STRING = {'type': 'string'}


def obj(**properties):
    return {'type': 'object', 'properties': properties}


def array(items):
    return {'type': 'array', 'items': items}


def schema():
    metadata = obj(name=STRING, namespace=STRING,
                   labels={'type': 'object', 'additionalProperties': STRING},
                   annotations={'type': 'object', 'additionalProperties': STRING})
    helm = obj(parameters=array(obj(name=STRING, value=STRING, forceString={'type': 'boolean'})),
               values=STRING, valueFiles=array(STRING))
    source = obj(repoURL=STRING, targetRevision=STRING, path=STRING, ref=STRING, chart=STRING,
                 helm=helm, kustomize=obj(images=array(STRING), namePrefix=STRING))
    app = obj(apiVersion=STRING, kind=STRING, metadata=metadata,
              spec=obj(project=STRING, source=source, sources=array(source),
                       destination=obj(server=STRING, namespace=STRING, name=STRING)))
    updater = obj(apiVersion=STRING, kind=STRING, metadata=metadata,
                  spec=obj(writeBackConfig=obj(method=STRING),
                           commonUpdateSettings=obj(updateStrategy=STRING, ignoreTags=array(STRING)),
                           applicationRefs=array(obj(namePattern=STRING, useAnnotations={'type': 'boolean'},
                               images=array(obj(alias=STRING, imageName=STRING,
                                   manifestTargets=obj(helm=obj(name=STRING, tag=STRING, spec=STRING),
                                                       kustomize=obj(name=STRING))))))))
    definitions = {"io.k8s.apimachinery.pkg.apis.meta.v1.ObjectMeta": metadata}
    for group, definition in zip(GROUPS, (app, updater)):
        kind, _ = GROUPS[group]
        definition['x-kubernetes-group-version-kind'] = [{'group': group, 'version': 'v1alpha1', 'kind': kind}]
        definitions[group + '.' + kind] = definition
    return {'swagger': '2.0', 'info': {'title': 'Provider regression fixture', 'version': '1'},
            'paths': {}, 'definitions': definitions}


def render_source(manifest):
    spec = manifest['spec']
    return spec['source'] if 'source' in spec else spec['sources'][0]


def images(manifest):
    source = render_source(manifest)
    return source.get('helm', {}).get('parameters', source.get('kustomize', {}).get('images', []))


def set_runtime_image(manifest, reference):
    source = render_source(manifest)
    if 'helm' in source:
        source['helm']['parameters'] = [{'name': 'image', 'value': reference}]
    else:
        source['kustomize']['images'] = ['app=' + reference]


def effective_image(manifest):
    current = images(manifest)[0]
    return current['value'] if isinstance(current, dict) else current.split('=', 1)[1]


class API(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.objects = {}
        self.requests = []
        self.external_image = None
        self.external_sources = None
        self.conflicts = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def failure(self, code, reason):
        self.respond(code, {'apiVersion': 'v1', 'kind': 'Status', 'status': 'Failure',
                            'message': reason, 'reason': reason, 'code': code})

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/version':
            return self.respond(200, {'major': '1', 'minor': '34', 'gitVersion': 'v1.34.0'})
        if path == '/api':
            return self.respond(200, {'kind': 'APIVersions', 'apiVersion': 'v1', 'versions': ['v1']})
        if path == '/api/v1':
            return self.respond(200, {'kind': 'APIResourceList', 'apiVersion': 'v1', 'groupVersion': 'v1', 'resources': []})
        if path == '/apis':
            groups = [{'name': group, 'versions': [{'groupVersion': group + '/v1alpha1', 'version': 'v1alpha1'}],
                       'preferredVersion': {'groupVersion': group + '/v1alpha1', 'version': 'v1alpha1'}} for group in GROUPS]
            groups.append({'name': 'apiextensions.k8s.io', 'versions': [{'groupVersion': 'apiextensions.k8s.io/v1', 'version': 'v1'}],
                           'preferredVersion': {'groupVersion': 'apiextensions.k8s.io/v1', 'version': 'v1'}})
            return self.respond(200, {'kind': 'APIGroupList', 'apiVersion': 'v1', 'groups': groups})
        if path == '/apis/apiextensions.k8s.io/v1':
            return self.respond(200, {'kind': 'APIResourceList', 'apiVersion': 'v1',
                'groupVersion': 'apiextensions.k8s.io/v1', 'resources': [{'name': 'customresourcedefinitions',
                'singularName': 'customresourcedefinition', 'namespaced': False, 'kind': 'CustomResourceDefinition', 'verbs': ['get', 'list']}]})
        if path == '/apis/apiextensions.k8s.io/v1/customresourcedefinitions':
            return self.respond(200, {'apiVersion': 'apiextensions.k8s.io/v1', 'kind': 'CustomResourceDefinitionList', 'items': []})
        if path == '/openapi/v2':
            return self.respond(200, schema())
        for group, (kind, plural) in GROUPS.items():
            if path == '/apis/' + group + '/v1alpha1':
                return self.respond(200, {'kind': 'APIResourceList', 'apiVersion': 'v1',
                    'groupVersion': group + '/v1alpha1', 'resources': [{'name': plural, 'singularName': plural[:-1],
                    'namespaced': True, 'kind': kind, 'verbs': ['get', 'list', 'create', 'update', 'patch', 'delete']}]})
        if path in self.server.objects:
            return self.respond(200, self.server.objects[path])
        return self.failure(404, 'NotFound')

    def do_PATCH(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((parsed.path, query, deepcopy(value)))
        assert self.headers['Content-Type'].startswith('application/apply-patch+'), self.headers
        if value['kind'] == 'Application' and self.server.external_image is not None:
            changed = (value['spec'].get('sources') != self.server.external_sources
                       if self.server.external_sources is not None else images(value) != self.server.external_image)
            if changed and query.get('force') != ['true']:
                assert query.get('force') == ['false'], query
                self.server.conflicts += 1
                return self.failure(409, 'Conflict')
        if value['kind'] == 'Application' and query.get('force') == ['true']:
            self.server.external_image = None
            self.server.external_sources = None
        if 'dryRun' not in query:
            self.server.objects[parsed.path] = deepcopy(value)
        return self.respond(200, value)

    def do_DELETE(self):
        path = urlsplit(self.path).path
        self.server.objects.pop(path, None)
        return self.respond(200, {'apiVersion': 'v1', 'kind': 'Status', 'status': 'Success'})


def strip_encryption(text):
    """Use test-local state; omit only KMS encryption from the actual module."""
    match = re.search(r'(?m)^  encryption \{', text)
    if match is None:
        return text
    start = text.index('{', match.start())
    depth = 1
    end = start + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[:match.start()] + text[end:]


def install_module(target, source):
    for path in target.glob('module-*.tf'):
        path.unlink()
    for path in source.glob('*.tf'):
        (target / ('module-' + path.name)).write_text(strip_encryption(path.read_text()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, default=ROOT)
    parser.add_argument('--plugin-dir', type=Path, help='Optional existing signed-provider installation directory')
    args = parser.parse_args()
    modules = args.module_root / 'IaC/terragrunt-catalog/modules'
    opted = modules / 'argocd-application-image-updater'
    default = modules / 'argocd-application-kubernetes'
    assert 'resource "kubernetes_manifest" "this"' in (opted / 'main.tf').read_text(), 'Application resource not implemented'
    assert shutil.which('tofu'), 'Run in the repository Nix development shell'
    with tempfile.TemporaryDirectory(prefix='image-updater-provider-') as directory:
        scratch = Path(directory)
        api = API()
        thread = Thread(target=api.serve_forever, daemon=True)
        thread.start()
        try:
            for multi, renderer in ((False, 'helm'), (True, 'helm'), (False, 'kustomize'), (True, 'kustomize')):
                case = scratch / (('multi' if multi else 'single') + '-' + renderer)
                case.mkdir()
                install_module(case, opted)
                (case / 'provider.tf').write_text('provider "kubernetes" {\n'
                    f'  host = "http://127.0.0.1:{api.server_port}"\n'
                    '  token = "local-fixture-only"\n}\n')
                env = {key: value for key, value in os.environ.items()
                       if not key.startswith(('KUBE_', 'TF_VAR_'))}

                def run(*command, succeeds=True):
                    result = subprocess.run(['tofu', command[0], '-no-color', *command[1:]], cwd=case, env=env,
                                            capture_output=True, text=True, timeout=90, check=False)
                    assert (result.returncode == 0) is succeeds, result.stdout + result.stderr
                    return result.stdout + result.stderr

                init = ['init', '-input=false']
                if args.plugin_dir:
                    init.append('-plugin-dir=' + str(args.plugin_dir.resolve()))
                run(*init)
                providers = run('providers')
                assert 'hashicorp/kubernetes' in providers and '3.2.1' in providers, providers
                name = 'fixture-' + case.name
                setting = 'values' if renderer == 'helm' else 'namePrefix'
                before = 'replicaCount: 1' if renderer == 'helm' else 'before-'
                after = 'replicaCount: 2' if renderer == 'helm' else 'after-'
                collection = 'parameters' if renderer == 'helm' else 'images'
                source = {'repoURL': 'https://example.invalid/repo', 'targetRevision': 'main',
                          'path': 'clusters/homelab/apps/fixture', renderer: {setting: before}}
                manifest = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
                            'metadata': {'name': name, 'namespace': 'argocd'},
                            'spec': {'project': 'default', 'destination': {'server': 'https://kubernetes.default.svc', 'namespace': 'fixture'}}}
                manifest['spec'].update({'sources': [source, {'repoURL': 'https://example.invalid/values',
                    'targetRevision': 'main', 'ref': 'values'}]} if multi else {'source': source})
                enrollment = {'paused': False, 'images': [{'alias': 'app', 'image_name': 'example.invalid/app:stable',
                    'source_paths': ['clusters/homelab/apps/fixture/values.yaml'],
                    renderer: {'spec': 'image'} if renderer == 'helm' else {'name': 'app'}}]}
                config = {'manifest': manifest, 'image_update': enrollment, 'kms_key_id': 'unused-test-local-state'}

                def save():
                    encoded = json.dumps(config)
                    assert 'sha256:' not in encoded, 'Resolved digests must stay outside configuration'
                    (case / 'terraform.tfvars.json').write_text(encoded)

                app_path = f'/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{name}'
                updater_path = f'/apis/argocd-image-updater.argoproj.io/v1alpha1/namespaces/argocd/imageupdaters/{name}'
                save()
                run('apply', '-auto-approve', '-input=false')
                assert app_path in api.objects and updater_path in api.objects
                live = api.objects[app_path]
                digest_b = 'example.invalid/app:stable@sha256:' + 'b' * 64
                set_runtime_image(live, digest_b)
                api.external_image = deepcopy(images(live))
                api.external_sources = deepcopy(live['spec'].get('sources'))
                unchanged = run('plan', '-input=false', '-detailed-exitcode')
                assert 'No changes' in unchanged, unchanged
                manifest['metadata']['labels'] = {'fixture': 'changed'}
                if not multi:
                    source[renderer][setting] = after
                    source['targetRevision'] = 'release'
                manifest['spec']['destination']['namespace'] = 'fixture-updated'
                enrollment['images'][0]['image_name'] = 'example.invalid/app:release'
                save()
                run('apply', '-auto-approve', '-input=false')
                assert effective_image(api.objects[app_path]) == digest_b
                assert render_source(api.objects[app_path])['targetRevision'] == source['targetRevision']
                assert render_source(api.objects[app_path])[renderer][setting] == source[renderer][setting]
                assert api.objects[app_path]['spec']['destination']['namespace'] == 'fixture-updated'
                assert api.objects[updater_path]['spec']['applicationRefs'][0]['images'][0]['imageName'].endswith(':release')
                if multi:
                    # Argo CD's sources list is atomic. Non-forced source edits
                    # require the explicit ownership handoff, even with digest B.
                    source['targetRevision'] = 'release'
                    source[renderer][setting] = after
                    save()
                    conflict = run('apply', '-auto-approve', '-input=false', succeeds=False)
                    assert 'Conflict' in conflict and effective_image(api.objects[app_path]) == digest_b
                    source['targetRevision'] = 'main'
                    source[renderer][setting] = before
                manifest['metadata']['labels']['fixture'] = 'race'
                save()
                run('plan', '-input=false', '-out=race.plan')
                digest_c = 'example.invalid/app:release@sha256:' + 'c' * 64
                set_runtime_image(api.objects[app_path], digest_c)
                api.external_image = deepcopy(images(api.objects[app_path]))
                api.external_sources = deepcopy(api.objects[app_path]['spec'].get('sources'))
                failed = run('apply', '-input=false', 'race.plan', succeeds=False)
                assert 'Conflict' in failed and api.conflicts > 0, failed
                assert effective_image(api.objects[app_path]) == digest_c
                # Pause and reconcile, then explicitly hand ownership back to default.
                enrollment['paused'] = True
                save()
                run('apply', '-auto-approve', '-input=false')
                assert api.objects[updater_path]['spec']['commonUpdateSettings']['ignoreTags'] == ['*']
                install_module(case, default)
                config.pop('image_update')
                # An override never present in configuration can remain in
                # object state during a paused source-edit handoff. Inspect
                # the real default provider payload; do not inject a digest.
                source[renderer][setting] = after
                source['targetRevision'] = 'release'
                save()
                run('plan', '-input=false', '-out=source-edit.plan')
                source_plan = json.loads(subprocess.check_output(['tofu', 'show', '-json', 'source-edit.plan'], cwd=case, env=env, text=True))
                source_changes = {change['address']: change['change']['actions'] for change in source_plan['resource_changes']}
                assert source_changes['kubernetes_manifest.this'] == ['update'], source_changes
                run('apply', '-input=false', 'source-edit.plan')
                assert effective_image(api.objects[app_path]) == digest_c, api.requests[-1]
                assert updater_path not in api.objects
                assert render_source(api.objects[app_path])['targetRevision'] == 'release'
                install_module(case, opted)
                config['image_update'] = enrollment
                save()
                run('apply', '-auto-approve', '-input=false')
                assert effective_image(api.objects[app_path]) == digest_c
                assert updater_path in api.objects
                install_module(case, default)
                config.pop('image_update')
                source[renderer][collection] = []
                source[renderer][setting] = after
                source['targetRevision'] = 'release'
                save()
                run('plan', '-input=false', '-out=handoff.plan')
                planned = json.loads(subprocess.check_output(['tofu', 'show', '-json', 'handoff.plan'], cwd=case, env=env, text=True))
                changes = {change['address']: change['change']['actions'] for change in planned['resource_changes']}
                assert changes['kubernetes_manifest.this'] == ['update'], changes
                assert changes['kubernetes_manifest.image_updater'] == ['delete'], changes
                run('apply', '-input=false', 'handoff.plan')
                assert images(api.objects[app_path]) == [] and updater_path not in api.objects
                assert render_source(api.objects[app_path])['targetRevision'] == 'release'
                # Recreate a missing Application from mutable bootstrap configuration.
                api.objects.pop(app_path)
                install_module(case, opted)
                config['image_update'] = enrollment
                source[renderer].pop(collection)
                save()
                run('apply', '-auto-approve', '-input=false')
                assert images(api.objects[app_path]) == []
                assert api.objects[updater_path]['spec']['applicationRefs'][0]['images'][0]['imageName'].endswith(':release')
                print(f'{name}: digest preservation, selector, conflict, pause, handoff and recreation passed')
            print(f'Actual kubernetes provider 3.2.1: {len(api.requests)} captured apply requests; {api.conflicts} non-forced conflicts')
        finally:
            api.shutdown()
            api.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
