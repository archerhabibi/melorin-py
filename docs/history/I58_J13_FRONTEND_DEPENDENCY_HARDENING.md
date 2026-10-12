# I58: J13 Frontend Dependency Hardening

Build-time tooling is now correctly isolated in `devDependencies` for both
web applications. Runtime dependencies contain only React, React DOM, and the
icon library, reducing the production dependency surface and preventing Vite,
PostCSS, Tailwind, and the React build plugin from being shipped as runtime
packages.

Both lockfiles were updated at the root dependency graph, and CI now runs
`npm audit --audit-level=high` independently for each application before the
build. Dependabot already tracks both npm manifests for follow-up security
patches.

The current project intentionally remains on the Tailwind 3/PostCSS pipeline
because the source and PostCSS config use the v3 integration. A major Tailwind
4 migration would require changing the build plugin and stylesheet contract,
not a blind version bump. CI is now fail-closed on high-severity findings so
the remaining registry-resolved advisories cannot be mistaken for a clean
release.
