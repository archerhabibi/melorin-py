# I21: Web dependency lockfiles

The hollow lockfiles were removed and the lockfile checker now fails when a
lockfile is missing or when a direct dependency lacks `resolved` and
`integrity` metadata. CI installs both Web manifests before running this check,
so the generated graph is validated rather than merely checking the root
metadata.

Before release, run `npm install --include=dev --no-audit --no-fund` in each Web
app and commit the generated `package-lock.json` files. This environment has
Node but no npm or package registry, so those two lockfiles could not be
generated here.
