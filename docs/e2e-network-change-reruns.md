# e2e: Requests Lost to Host Network Changes

**Task:** #419
**Code:** [`tests/e2e/conftest.py`](../tests/e2e/conftest.py), section "Requests lost to host network changes"
**Test:** [`tests/unit/test_e2e_network_change_reruns.py`](../tests/unit/test_e2e_network_change_reruns.py)

---

## 1. What net::ERR_NETWORK_CHANGED Means Here

Chromium's Linux address tracker reports every IP address added to or removed from the
host. That includes the IPv6 link-local address of each Docker veth interface, which
comes and goes with its container. On each such report Chromium fails every request
still waiting for a connection, loopback ones included, with `net::ERR_NETWORK_CHANGED`,
before sending it. A request already on a connected socket is unaffected.

## 2. Why the e2e Live Server Is Exposed

The e2e live server is werkzeug's development server, which closes every connection
after its response. So each request a page makes first waits for a new socket, and an
address change in that window loses the request.

## 3. What It Looks Like

- A deferred script such as the vendored Alpine core is lost, so Alpine never starts.
  The first click after `page.goto` times out after 30 s with `<aside> ... intercepts
  pointer events`, or `page.evaluate` raises `ReferenceError: Alpine is not defined`.
- The live server's log has no line for the lost GET. On `/simulate/home` it has none for
  `GET /api/presets` either, which the page's Alpine component would have made.
- A test that collects console errors sees
  `Failed to load resource: net::ERR_NETWORK_CHANGED`.

## 4. The Policy

[`tests/e2e/conftest.py`](../tests/e2e/conftest.py) records, for each attempt at an e2e
test, every request the test's browser context fails with exactly
`net::ERR_NETWORK_CHANGED`, from any origin. A test that fails after such a loss runs
once more, through pytest-rerunfailures' `flaky` marker, and pytest shows the failed
attempt as `RERUN`. A test that still fails lists the requests its last attempt lost in a
section of its failure output, `requests Chromium failed with net::ERR_NETWORK_CHANGED`.

Nothing else is rerun. A failure without such a loss, or after a request lost to any
other error, fails at once: those errors can be the app's or the test's own doing.

## 5. How to Reproduce

1. Serve a page that fires 7 fetches at an endpoint that answers after 20 s. Chromium
   opens 6 HTTP/1.1 sockets per host, so the 7th waits for one.
2. Run `ip -ts monitor address` alongside, on a host that starts and stops containers.
3. The waiting request fails with `net::ERR_NETWORK_CHANGED` within about 100 ms of a
   veth address add or delete, and the server never receives it. Chromium's
   `--log-net-log` shows `NETWORK_IP_ADDRESSES_CHANGED` at those moments.
