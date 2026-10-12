# I59: Reports and Referral Modules

J14's empty `reports` and `partner` scaffolds no longer represent the
implemented surface. The reports module now exposes store-scoped sales
breakdowns and currency-grouped successful payment totals for administrators.

The referral module now has explicit API routes: users can see their referral
code and commission history, while administrators can list and upsert
store/product-specific signup and commission rules. Existing first-touch
attribution, immutable ledger postings, refund reversals, and clawback offsets
remain in the referral service; the new read/configuration layer does not
rewrite financial history.
