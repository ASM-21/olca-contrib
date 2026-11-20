# Comment for GreenDelta/olca-ipc.py#41

https://github.com/GreenDelta/olca-ipc.py/issues/41

## Comment (paste as is)

A status note for anyone who finds this issue:

The growth comes from `CalculationQueue.nextSimulation` in olca-modules. Up
to v2.7.0 it replaced the previous result (`state.updateResult(null)`)
without disposing it. Each result holds a matrix factorization in native
memory (UMFPACK or PARDISO) that only `dispose()` frees, so every
`simulate_next()` loses one.

This is fixed in olca-modules c895e0e ("also, dispose old simulation
results"), which is in the olca-modules v2.7.1 tag, so this issue may be
closable once openLCA 2.7.1 is released. On the client side, olca-ipc
2.7.0 (with #49) no longer loses `simulate_next()` errors and still
disposes a result after a later error.

Until then, with openLCA 2.7.0 and earlier, the leak-free workaround is
the one in the original post: a new simulation for each iteration,
disposed after reading its results. Running `simulate_next()` in chunks
and disposing the simulator between chunks does not help, because
disposing frees only the current run, and the runs replaced before it
are already lost.
