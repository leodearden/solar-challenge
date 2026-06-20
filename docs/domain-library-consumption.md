# Domain Library Consumption Guide

This document is the consumer-facing recipe for depending on the
`solar_challenge` domain library from a separate repository (e.g. the
`solar_challenge_platform` worktree) using the **git+file pinned** model.

The authoritative public surface is `solar_challenge.__all__` (defined in
`src/solar_challenge/__init__.py`), which is frozen and contract-tested by
`tests/unit/test_init_lazy_surface.py`.

---

## Pinned dependency recipe

Add the following line to the consuming project's `pyproject.toml`
`[project]` `dependencies` list:

```toml
dependencies = [
  "solar-challenge @ git+file:///home/leo/src/my-solar-challenge@<release-tag>",
]
```

**Worked example** (P0 freeze tag):

```toml
dependencies = [
  "solar-challenge @ git+file:///home/leo/src/my-solar-challenge@solar-challenge-v0.1.0",
]
```

After editing, run `uv lock` and commit the updated `uv.lock` alongside the
`pyproject.toml` change.  The lockfile is the reproducibility contract — never
leave it uncommitted.

---

## Why pinned, not an editable path

An editable `pip install -e /path/to/my-solar-challenge` (or a `path =`
dependency) resolves against the **live main checkout** shared by all
worktrees.  Any `git merge` into `main` deploys the change underneath every
in-flight worktree immediately — no review step, no lockfile bump, no CI gate.

The git+file pin **insulates** each consuming worktree:

- The resolved wheel is content-addressed at the tag SHA, not the tip of main.
- Breaking API changes on main cannot reach the consumer until a deliberate
  pin-bump PR is merged.
- Parallel worktrees running their own verify steps see the same pinned surface
  throughout, giving reproducible results.

---

## Upgrade workflow

1. Cut (or check out) the new release tag on `my-solar-challenge`
   (see [Tag / release convention](#tag--release-convention) below).
2. In the consuming project, update the tag in `pyproject.toml`:

   ```toml
   "solar-challenge @ git+file:///home/leo/src/my-solar-challenge@solar-challenge-vX.Y.Z"
   ```

3. Run `uv lock` — this re-resolves the wheel from the new tag SHA.
4. Commit both `pyproject.toml` and `uv.lock` together as a single reviewed
   platform commit with a message like:
   `chore(deps): bump solar-challenge to solar-challenge-vX.Y.Z`.
5. Open a PR; CI verifies the new surface before merge.

---

## Tag / release convention

Tags use the prefix `solar-challenge-` followed by a semantic version:

```
solar-challenge-v0.1.0   ← P0 API freeze (first pinnable release)
solar-challenge-v0.2.0   ← next minor (additive surface changes)
solar-challenge-v1.0.0   ← first stable / breaking-change boundary
```

**P0 cuts the first freeze tag** — that tag IS the literal API freeze, i.e.
`solar_challenge.__all__` is considered stable from that point.

Bumping the pin in a consuming project is a **deliberate, reviewed consumer
commit** (not an automatic update).  The tag convention makes the intent of
each bump self-documenting in git history.

---

## Consumption caveats

### Cheap top-level import

```python
import solar_challenge          # fast — no pvlib, no network I/O
```

`import solar_challenge` executes the `__init__` module only, which is
pvlib-free.  The frozen `__all__` and the PEP-562 `__getattr__` lazy loader
are registered, but no submodule is imported until a public name is accessed.

### Lazy pvlib dependency

Accessing any name from `pv` or `weather` triggers `importlib.import_module`
for that submodule, which pulls `pvlib` transitively:

```python
sc = solar_challenge
mc = sc.create_model_chain(...)    # ← first access imports pv.py + pvlib
tmy = sc.get_tmy_data(...)         # ← first access imports weather.py + pvlib
```

Consumers that want to avoid the pvlib cost must not touch these symbols.

### Network I/O

`weather.get_tmy_data` makes an **outbound HTTPS request to the PVGIS API**.
In test environments and CI, consumers **must inject a mock or a pre-cached
`WeatherCache`** rather than calling `get_tmy_data` directly:

```python
import solar_challenge

# Inject a pre-built cache instead of hitting the network
solar_challenge.set_weather_cache(my_test_cache)
```

---

## Frozen public surface

The authoritative public surface is `solar_challenge.__all__`, defined in
`src/solar_challenge/__init__.py`.  It is frozen and contract-tested by
`tests/unit/test_init_lazy_surface.py`, and enforced at import time via the
module's `__getattr__` guard.  Consumers should reference `__all__` directly
rather than relying on any copy maintained in this document.
