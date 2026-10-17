#!/usr/bin/env python3
"""Validate Octelium's unauthenticated HTTP/2 gRPC response independently of transport."""
import re


def fields(lines):
    """Parse field names exactly and retain duplicates for validation."""
    result = {}
    for line in lines:
        name, colon, value = line.partition(b":")
        if not colon or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            return None
        result.setdefault(name.lower(), []).append(value.strip(b" \t"))
    return result


def final_response(data):
    """Separate curl's final response headers from its following HTTP trailers."""
    status, headers, trailers = None, None, {}
    for block in re.split(rb"\r?\n\r?\n", data):
        lines = block.splitlines()
        if not lines:
            continue
        match = re.fullmatch(rb"HTTP/(1\.[01]|2|3) ([1-5][0-9]{2})(?:[ \t].*)?", lines[0])
        if match:
            status, headers, trailers = match.groups(), fields(lines[1:]), {}
            if headers is None:
                return None
        else:
            following = fields(lines)
            if headers is None or following is None:
                return None
            for name, values in following.items():
                trailers.setdefault(name, []).extend(values)
    return (headers, trailers) if status == (b"2", b"200") else None


def has_status_16(headers):
    return headers is not None and headers.get(b"grpc-status") == [b"16"]


def unauthenticated(headers, body, *, native):
    protocol = "application/grpc" if native else "application/grpc-web+proto"
    response = final_response(headers)
    if response is None:
        return False
    response_headers, http_trailers = response
    content_types = response_headers.get(b"content-type", [])
    accepted_types = {protocol.encode(), b"application/grpc+proto"} if native else {protocol.encode()}
    if (len(content_types) != 1 or b"content-type" in http_trailers
            or content_types[0].split(b";", 1)[0].strip(b" \t").lower() not in accepted_types):
        return False
    payload = body
    if native:
        if b"grpc-status" in response_headers:
            return not payload and b"grpc-status" not in http_trailers and has_status_16(response_headers)
        return has_status_16(http_trailers)
    if b"grpc-status" in http_trailers:
        return False
    # gRPC-Web permits a trailers-only response in the headers with no body.
    if not payload:
        return has_status_16(response_headers)
    if b"grpc-status" in response_headers:
        return False
    # Responses with a body must finish with a length-prefixed trailer frame.
    while len(payload) >= 5:
        flag, length = payload[0], int.from_bytes(payload[1:5], "big")
        if len(payload) < 5 + length:
            return False
        frame, payload = payload[5:5 + length], payload[5 + length:]
        if flag == 128:
            return not payload and has_status_16(fields(frame.splitlines()))
    return False
