package main

import rego.v1

test_rejects_mutable_external_git_revision if {
	violations := deny with input as external_git_application("v0.0.36")
	some msg in violations
	contains(msg, "external Git source must use an exact commit SHA")
}

test_allows_exact_external_git_revision if {
	violations := deny with input as external_git_application("5d4bfc84b32cd9c5f56ed3aba921b1a3924ea2f0")
	count(violations) == 0
}

test_rejects_mutable_external_git_multi_source if {
	violations := deny with input as {
		"apiVersion": "argoproj.io/v1alpha1",
		"kind": "Application",
		"metadata": {"name": "external-multi-source"},
		"spec": {"sources": [{
			"repoURL": "https://github.com/example/repository",
			"path": "deploy/chart",
			"targetRevision": "main",
		}]},
	}
	count(violations) == 1
}

test_rejects_mutable_external_git_ref_source if {
	violations := deny with input as {
		"apiVersion": "argoproj.io/v1alpha1",
		"kind": "Application",
		"metadata": {"name": "external-ref-source"},
		"spec": {"sources": [{
			"repoURL": "https://github.com/example/values",
			"ref": "values",
			"targetRevision": "main",
		}]},
	}
	count(violations) == 1
}

external_git_application(revision) := {
	"apiVersion": "argoproj.io/v1alpha1",
	"kind": "Application",
	"metadata": {"name": "external-git-source"},
	"spec": {"source": {
		"repoURL": "https://github.com/example/repository",
		"path": "deploy/chart",
		"targetRevision": revision,
	}},
}
