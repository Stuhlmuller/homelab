"""Rewrite reviewed generated Pod images to their pinned Harbor copies."""
import base64
import json
import re
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CATALOG = "/app/images.json"
HARBOR = "harbor.stinkyboi.com/mirror/"


def normalize(image):
    name, separator, digest = image.partition("@")
    first = name.split("/", 1)[0]
    if "/" not in name or ("." not in first and ":" not in first and first != "localhost"):
        name = "docker.io/" + name
    if name.startswith("docker.io/") and name.count("/") == 1:
        name = name.replace("docker.io/", "docker.io/library/", 1)
    if ":" not in name.rsplit("/", 1)[-1] and not separator:
        name += ":latest"
    return name + ("@" + digest if separator else "")


def repository_digest(image):
    name, _, digest = normalize(image).partition("@")
    if ":" in name.rsplit("/", 1)[-1]:
        name = name.rsplit(":", 1)[0]
    return name + "@" + digest


def destinations(catalog):
    result = {}
    for item in catalog["images"]:
        source = item["source"]
        name, sep, digest = source.partition("@")
        if not sep or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            raise ValueError("catalog source needs a digest")
        key = normalize(name)
        dest = HARBOR + (name if ":" in name.rsplit("/", 1)[-1] else name + ":" + digest.removeprefix("sha256:")) + "@" + digest
        if ":" in name.rsplit("/", 1)[-1]:
            if key in result and result[key] != dest:
                raise ValueError("conflicting catalog source: " + key)
            result[key] = dest
        result[normalize(source)] = dest
        result[repository_digest(source)] = dest
    return result


def mutate(review, mapping):
    request = review["request"]
    uid = request["uid"]
    pod = request["object"]
    subresource = request.get("subResource", "")
    groups = ("ephemeralContainers",) if subresource == "ephemeralcontainers" else ("initContainers", "containers", "ephemeralContainers")
    patch = []
    for group in groups:
        for index, container in enumerate(pod.get("spec", {}).get(group, [])):
            source = container["image"]
            target = mapping.get(normalize(source))
            if target is None and "@" in source:
                target = mapping.get(repository_digest(source))
            if target is None and source in mapping.values():
                continue
            if target is None:
                return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview", "response": {
                    "uid": uid, "allowed": False, "status": {"message": "unreviewed image: " + source}}}
            if source != target:
                patch.append({"op": "replace", "path": f"/spec/{group}/{index}/image", "value": target})
    response = {"uid": uid, "allowed": True}
    if patch:
        response["patchType"] = "JSONPatch"
        response["patch"] = base64.b64encode(json.dumps(patch, separators=(",", ":")).encode()).decode()
    return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview", "response": response}


class Handler(BaseHTTPRequestHandler):
    mapping = None

    def do_GET(self):
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/mutate":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(length))
            response = mutate(request, self.mapping)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    with open(CATALOG, encoding="utf-8") as source:
        Handler.mapping = destinations(json.load(source))
    server = ThreadingHTTPServer(("0.0.0.0", 9443), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("/tls/tls.crt", "/tls/tls.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
