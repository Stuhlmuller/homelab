#!/bin/sh
# Consume the request headers, then close a complete fixed response.
while IFS= read -r line; do
  [ "$line" = "$(printf '\r')" ] && break
done
printf 'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\nfixture-ok\n'
