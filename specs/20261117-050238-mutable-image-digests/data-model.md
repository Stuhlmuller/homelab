# Data Model

## Enrollment input

`image_update` is optional per Application stack. Absence selects the unchanged
registration module. Presence selects the runtime-owned image module.

Fields: stable application identity from manifest metadata; mode inferred and
validated from exactly one render source; `images` with unique alias, registry
repository plus mutable tag, and Helm image parameter names or Kustomize original
image name; exact repository-relative `source_paths` for owned workload files;
optional paused state. No digest, semver-update policy, wildcard
application selection, Git credential or write-back branch input is accepted.

## Native controller configuration

One native ImageUpdater CR per enrolled Application, namespace `argocd`, exact
application selector, digest strategy, Argo CD write-back. Images map one-to-one
to declared enrollment entries. The CR is owned by the opt-in module; the
Application's image override collection is owned by the updater.

## Application ownership

Registration owns identity, source URLs/paths/revisions, value files and normal
values, destination, project and synchronization policy. The updater creates and owns Helm `parameters` or Kustomize `images` in the sole
render source; these keys must be absent from desired Application configuration.
Empty or seeded collections reject enrollment. Each source path must belong to the
Application source/value files, and its package occurrences must be exclusively
owned by that enrollment. Exact package/file Renovate exclusions are required;
Harbor policy exceptions additionally match the normalized repository and tag
and retain existing source provenance requirements. Provider manifest and refreshed object
are distinct representations; tests must preserve this distinction.

## Transitions

Unenrolled → validated enrollment → active or paused. Active selector changes
retain ownership while changing the lookup target. Paused retains the effective
hash. Removal first reconciles pause, then selects the default module with an
explicit empty/replacement override collection and restores the corresponding
package/file Renovate ownership. The provider regression proves the handoff;
merely omitting old override fields is insufficient. Recreation resolves the current declared selector again. Lookup failure
retains the last effective content and reports an error.

## Temporary source-edit handoff

A separate `image_update_handoff` stack object records paused enrollment metadata
only while `image_update` is absent. It retains exact image/source-path ownership
for policy and Renovate validation but creates no native CR or runtime module.
Its shape is the same image mapping with `paused = true`; active enrollment and
handoff are mutually exclusive. The ordinary module omits runtime overrides and
preserves their live values for a source edit; reenrollment removes the handoff
record. Permanent removal removes both records and explicitly clears/replaces
the collection. This metadata is not a digest and is not a second registry.
