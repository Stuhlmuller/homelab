import assert from "node:assert/strict";
import test from "node:test";

import { findHeading, readerLink } from "../../clusters/homelab/apps/openwiki/site/client-lib.js";

const source = "https://github.com/Stuhlmuller/homelab/blob/main/";

test("repository links resolve against the originating wiki page", () => {
  assert.deepEqual(readerLink("quickstart", "../docs/application-recovery.md"), {
    url: source + "docs/application-recovery.md",
    id: null,
    fragment: "",
  });
  assert.equal(readerLink("operations/wiki-maintenance", "../../IaC/homelab/us-west-2/apps/openwiki/stack.hcl").url,
    source + "IaC/homelab/us-west-2/apps/openwiki/stack.hcl");
});

test("internal and same-page links preserve the section fragment", () => {
  assert.deepEqual(readerLink("operations/audit-2026-09-04", "validation-gates.md#istio-ambient-recovery"), {
    url: source + "openwiki/operations/validation-gates.md#istio-ambient-recovery",
    id: "operations/validation-gates",
    fragment: "istio-ambient-recovery",
  });
  assert.equal(readerLink("operations/validation-gates", "#caf%C3%A9").fragment, "café");

  const headings = ["Overview", "Istio Ambient Recovery", "Istio Ambient Recovery"]
    .map((textContent) => ({ textContent }));
  assert.equal(findHeading(headings, "istio-ambient-recovery"), headings[1]);
  assert.equal(findHeading(headings, "istio-ambient-recovery-1"), headings[2]);
});

test("explicit external links and invalid paths keep their existing handling", () => {
  for (const href of ["https://example.com/reference.md", "//example.com/wiki.md", "/graph.json", "../../../outside", "#%broken"]) {
    assert.equal(readerLink("quickstart", href), null, href);
  }
});
