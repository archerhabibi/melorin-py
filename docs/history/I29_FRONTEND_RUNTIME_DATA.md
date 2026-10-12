# I29: frontend runtime data

The storefront no longer ships hard-coded demo plans. It renders only the
catalog returned by Core and shows an explicit unavailable state when Core
cannot provide catalog data.

The admin dashboard already loads orders, users, tickets, stores, health, and
backup data from Core. Remaining browser acceptance work belongs in the Web
build and staging smoke gate.
