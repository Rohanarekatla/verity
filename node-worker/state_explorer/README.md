# node-worker/state_explorer/

State Explorer — enumerates bounded UI states (modals, menus, error
states) so they can be audited too. Split from the Crawler on purpose:
state enumeration is where combinatorial blowup happens, and isolating
it keeps the Crawler simple and the budget enforceable.

Not yet implemented — Week 17, per the Execution Plan.
