---
name: terragrunt-find-filter
description: Use Terragrunt find and --filter commands to discover and target specific infrastructure units and stacks.
---

# Terragrunt Find and Filter

Use the `terragrunt find` command to discover Terragrunt configurations (units and stacks) in your codebase, and the `--filter` flag to target specific units and stacks using a flexible query language.

## Overview

Terragrunt provides two key commands for infrastructure discovery and targeting:

- **`terragrunt find`** – Recursively searches for `terragrunt.hcl` and `terragrunt.stack.hcl` files and displays them in formatted output.
- **`terragrunt --filter`** – Targets specific units and stacks using a flexible query language (name, path, attributes, negation, graph traversal, etc.).

## Terragrunt Find

### Basic Usage

```sh
# Find all configurations (units and stacks) in the current directory
terragrunt find

# Find all configurations in a different directory
terragrunt find --working-dir /path/to/working/dir

# Disable color output
terragrunt find --no-color

# Output as JSON
terragrunt find --format=json
terragrunt find --json
```

### Filtering Results

The `--filter` flag provides a powerful query language for targeting specific configurations.

#### Name-Based Filtering

Match configurations by their name using exact matches or glob patterns:

```sh
# Exact match
terragrunt find --filter app1

# Glob pattern
terragrunt find --filter 'app*'
```

#### Path-Based Filtering

Match configurations by their file system path:

```sh
# Relative paths with glob
terragrunt find --filter './envs/prod/**'
# Absolute path
terragrunt find --filter '/absolute/path/to/envs/dev/apps/*'
```

#### Attribute-Based Filtering

Match configurations by their configuration attributes:

```sh
# Filter by type
terragrunt find --filter 'type=unit'
terragrunt find --filter 'type=stack'

# Filter by external dependency
terragrunt find --filter 'external=false'
```

#### Negation

Exclude configurations using the `!` prefix:

```sh
# Exclude specific configuration
terragrunt find --filter '!app1'

# Exclude by path
terragrunt find --filter '!./prod/**'
```

#### Intersection (Refinement)

Use the `|` operator to refine results with multiple filters:

```sh
# Find all units in prod directory
terragrunt find --filter './prod/** | type=unit'

# Chain multiple filter expressions
terragrunt find --filter './dev/** | type=unit | !name=unit1'
```

#### Graph-Based Filtering

Filter configurations based on dependency relationships using graph traversal operators:

```sh
# Include target and all dependencies (things it depends on)
terragrunt find --filter 'service...'

# Include target and all dependents (things that depend on it)
terragrunt find --filter '...service'

# Include target, dependencies, and dependents
terragrunt find --filter '...service...'

# Find dependencies of a unit but exclude the unit itself
terragrunt find --filter '^service...'
```

#### Git Filtering

Filter configurations based on changes between Git references:

```sh
# Find components affected by changes between main and HEAD
terragrunt find --filter-affected

# Compare between two specific references
terragrunt find --filter '[main...HEAD]'
# Compare between specific commits
terragrunt find --filter '[abc123...def456]'
```

## Terragrunt Filter Syntax

### Name Expressions

Match units and stacks by their name:

```sh
terragrunt find --filter 'name=web'
terragrunt find --filter 'name=*'
```

### Path Expressions

Match units and stacks by their file system path:

```sh
terragrunt find --filter './prod/**'
terragrunt find --filter './envs/prod/**'
```

### Attribute Expressions

Match units and stacks by their configuration attributes:

```sh
terragrunt find --filter 'type=unit'
terragrunt find --filter 'type=stack'
terragrunt find --filter 'external=false'
```

### Graph Expressions

Use graph traversal operators:

| Operator | Meaning |
| --- | --- |
| `...` | Include target and all dependencies (things it depends on) |
| `...^` | Include target and all dependents (things that depend on it) |
| `......` | Include target, dependencies, and dependents |
| `^...` | Include only dependencies (exclude target) |
| `...^...` | Include dependencies and dependents (exclude target) |

### Combining Expressions

Use the `|` operator to combine multiple filters with OR logic:

```sh
terragrunt find --filter 'unit1' --filter 'stack1'
```

### Negated Expressions

Exclude configurations using the `!` prefix:

```sh
terragrunt find --filter '!app1'
```

## Common Workflows

### Discover All Units

```sh
# Find all units and stacks in the current directory
terragrunt find
```

### Find Units by Name

```sh
# Find all units named "web"
terragrunt find --filter 'name=web'

# Find all units matching a glob pattern
terragrunt find --filter 'app*'
```

### Filter by Path

```sh
# Find all units in the prod environment
terragrunt find --filter './prod/** | type=unit'

# Find all units in a specific directory
terragrunt find --filter './envs/prod/** | type=unit'
```

### Filter by Attribute

```sh
# Find only unit-type units
terragrunt find --filter 'type=unit'

# Find only stack-type units
terragrunt find --filter 'type=stack'

# Find units that are not external
terragrunt find --filter 'external=false'
```

### Graph-Based Discovery

```sh
# Find a service and all its dependencies
terragrunt find --filter 'service...'

# Find a service and all units that depend on it
terragrunt find --filter '...service'

# Find the complete dependency graph for a unit
terragrunt find --filter '...db...'
```

### Git Filter Expressions

```sh
# Find components affected by changes between main and HEAD
terragrunt find --filter-affected

# Compare between two specific references
terragrunt find --filter '[main...HEAD]'
```

## Output Formats

### Text Format (Default)

Displays each configuration on a new line with color coding:

- **Units** – blue
- **Stacks** – green

### JSON Format

Outputs results in JSON format, including metadata about each configuration (type, path, dependencies, etc.):

```sh
# JSON output
terragrunt find --format=json

# Or the shorter alias
terragrunt find --json
```

## Integration with Other Terragrunt Commands

These filter-based queries can be combined with other Terragrunt commands for targeted operations:

```sh
# Plan only affected units
terragrunt run --all --filter 'type=unit' -- plan

# Apply only specific units
terragrunt run --all --filter 'name=web' -- apply

# Validate only certain stacks
terragrunt hcl validate --filter 'type=stack'
```

## Best Practices

1. **Use `--filter` instead of queue control flags** – The filter flag provides a more powerful and flexible way to target infrastructure.
2. **Combine filters with `|`** – Use the OR operator to refine results when you need multiple criteria.
3. **Leverage graph expressions** – Use `...` and `^` operators to explore dependency relationships.
4. **Use `--filter-affected`** – To find components changed between branches or commits.
5. **Output as JSON** – When you need to programmatically process the results.

## See Also

- [Terragrunt Find](https://terragrunt.gruntwork.io/docs/reference/cli/commands/find/)
- [Terragrunt Filter](https://terragrunt.gruntwork.io/docs/features/filter/)
- [Terragrunt Filter Syntax Overview](https://terragrunt.gruntwork.io/docs/features/filter/syntax-overview/)
