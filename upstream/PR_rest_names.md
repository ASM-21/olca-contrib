# Pull request for GreenDelta/olca-ipc.py

Branch: `ASM-21:fix-rest-names`, based on `6b8db74` ("add usage searcg"),
which is the 2.7.0 release.
Patch file: `0001-Fix-names-in-the-REST-paths-of-the-RestClient.patch`.

## Title

Fix names in the REST paths of the RestClient

## Description (paste as is)

Hi Michael,

this fixes two small bugs with names in the REST paths of the `RestClient`
(both are in 2.7.0):

- `get(model_type, name=...)` puts the raw name into the path `name/{name}`.
  requests then cuts it at a `#` (fragment) or a `?` (query), and turns a
  valid escape like `%41` into `A`, so the server looks up a different name:
  `#2 fuel oil` arrives as an empty name and `steel? or iron` as `steel`.
  The name is now percent-encoded. A `/` is kept, because the route
  `name/<name>` in gdt-server accepts slashes, and so are the other
  characters that requests sends unchanged. On 20,000 random names, the
  request is byte-for-byte the same as before unless the name contains `#`,
  `?`, or a `%XX` sequence, so the `yoghurt, 12% fat` case is unchanged.
- `get_descriptor(model_type, name=...)` requests `name/{name}/info`. The
  REST API has no such route (the docs only list `{id}/info`), and the route
  `name/<name>` takes `/info` as part of the name, so it never returns the
  descriptor. It now calls `find`, which searches the descriptors of the
  type and returns the same fields as the ID route. Fetching the entity by
  name and calling `to_ref()` would be a single request, but the reference
  would then lack the location, flow type, process type, and reference unit.
  Happy to change that if you prefer.

I added two tests to `tests/test_rest_paths.py` that fail on master. Like
the other tests in that file, they need no server; I did not run the main
suite against a live server.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_019GyumPCFYjWH1cVefmqSoG
