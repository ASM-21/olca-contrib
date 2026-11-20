# Comment for GreenDelta/olca-ipc.py#4 (optional, after the PR)

https://github.com/GreenDelta/olca-ipc.py/issues/4

Post this only after the REST pull request has a response. It offers a
second contribution and asks about the API shape first, since it is
msrocka's own issue.

## Comment (paste as is)

Hi Michael, would you take a pull request for this? A client-side version
needs no server change: `get_all(o.UnitGroup)` once, then index the units by
name and ID. For example:

```python
def get_unit(self, uid: str | None = None, name: str | None = None) -> o.Unit | None
def find_unit(self, name: str) -> o.Ref | None
```

on `ProtoClient`, so both clients get it. Returning the unit group (and its
default flow property) as well would help when building exchanges. I would
match whatever shape you prefer.
