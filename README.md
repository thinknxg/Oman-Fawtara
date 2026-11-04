# thinkNXG Oman Fawtara

Oman VAT compliance, VAT return preparation and Fawtara e-invoicing for **thinkNXG ERP (ERPNext v16)** on the **thinkNXG Framework (Frappe v16)**.

`oman_fawtara` is a standalone, installable app. It extends ERPNext rather than replacing it: ERPNext still computes taxes, totals and the General Ledger; this app classifies every line, checks it against a versioned Oman VAT rule set, records an immutable VAT ledger, prepares the return and sends e-invoices through an accredited service provider.

Three design principles:

| Principle | How it is implemented |
|---|---|
| **Tax correctness** | The VAT *treatment* is separate from the *rate*. Rates and rules carry effective-from/to dates and a rule-set version, and are evaluated at each document's tax point. |
| **ERPNext-native** | It reuses Sales/Purchase Invoice, Item Tax Templates, Taxes and Charges templates, Journal Entry and the GL. It reads the v16 relational `Item Wise Tax Detail` (not the legacy JSON field) and reconciles to ERPNext's tax rows. It never overrides the ERPNext tax total. |
| **Auditable compliance** | Each document gets an immutable `Oman VAT Transaction` with a content hash. Returns are frozen into hashed snapshots. A hash-chained `Oman Compliance Audit Log` records compliance events, and each Fawtara submission keeps its attempts, receipts and archive. |

---

## 1. Requirements and installation

* thinkNXG Framework / Frappe **v16**, thinkNXG ERP / ERPNext **v16**, Python 3.14, Node 24 (as required by Frappe v16)

```bash
bench get-app https://github.com/<your-org>/oman_fawtara   # or unzip into apps/
bench --site <site> install-app oman_fawtara
bench --site <site> migrate
```

Installing the app:

* creates its 43 DocTypes, 11 reports, the **Oman Fawtara** workspace, the v16 Sidebar and Dock entries, and a Desktop Icon for grid mode;
* adds custom fields (prefixed `oman_`) to Sales Invoice, Purchase Invoice, their item tables, Customer, Supplier, Item, UOM and Journal Entry;
* seeds roles, VAT treatments, VAT codes, dated rates, return boxes, validation rules, recovery profiles, evidence types and a **simulated** sandbox provider.

Uninstalling (`bench --site <site> uninstall-app oman_fawtara`) removes the custom fields and the app's roles if no user holds them. Journals the app posted stay in place, because they are standard ERPNext accounting. Export your returns, snapshots, e-invoice archive and audit log first: uninstall drops the app's own tables.

## 2. Go-live configuration (in order)

1. **Company setup.** In the console or via API, run `oman_fawtara.setup.company_setup.setup_company(company, vatin, legal_name, effective_from, "Quarterly", first_period_start)`. It creates the VAT accounts, `Oman VAT 5%` and `Oman VAT 0%` Item Tax Templates, the Sales and Purchase Taxes templates, the template ↔ VAT-code mapping, the Account Mapping, the VAT Registration and the first four periods.
2. **Oman VAT Registration.** Enter the CR number, registered address, return frequency, and for Fawtara: the provider, electronic address and threshold figures.
3. **Parties.** Set `Oman VAT Status`, `Country (VAT)` and Tax ID on customers and suppliers, plus buyer type and electronic address for e-invoicing.
4. **Items.** Optionally set a default Sales/Purchase VAT Code and the Supply Category (Goods/Services). Supply category drives reverse-charge and import detection.
5. **Legal review (mandatory before production).** Have an Oman VAT specialist review the rules, rates and return boxes. Then, as an **Oman VAT Approver**, tick *Legal Rule-set Reviewed for Production* in **Oman VAT Settings** and record the reference. Production Fawtara providers cannot be enabled until this is done.
6. **Existing invoices.** Invoices submitted before the app was installed, or after a reinstall, have no VAT ledger entries, and return validation will flag them. Run `oman_fawtara.vat.transaction.backfill(company, from_date, to_date, dry_run=1)`, review the output, then run it again with `dry_run=0`. Each invoice is re-analysed with the rules at its tax point and recorded; no journals are posted. The GL reconciliation then shows anything historic that needs explaining.
7. **Fawtara.** Create the accredited provider (an adapter, see §6), confirm CustomizationID, ProfileID and endpoint scheme against the published PINT-OM specification, then enable **Oman Fawtara Settings**.

## 3. VAT engine

### Treatments (independent of rate)

| Treatment | Nature | Rate | Handling |
|---|---|---|---|
| Standard Rated | Standard | 5% | Output / input VAT |
| Zero Rated · Zero Rated Export | Zero Rated | 0% | Taxable; input recoverable; evidence required |
| Exempt | Exempt | 0% | No output VAT; feeds apportionment |
| Out of Scope | Out of Scope | — | Outside Oman VAT |
| Reverse Charge · Import of Services | Standard, self-assessed | 5% | Output and input self-assessed by the recipient |
| Import of Goods | Standard, customs | 5% | VAT assessed on the Bayan declaration |
| Mixed Use Expense | Standard | 5% | Partial recovery profile |
| Blocked Input VAT | Standard | 5% | Input VAT non-recoverable |

Each invoice line stores: `oman_vat_treatment`, `oman_vat_code`, `oman_vat_rate`, `oman_taxable_amount`, `oman_output_vat`, `oman_input_vat`, `oman_recovery_percentage`, `oman_recoverable_vat`, `oman_nonrecoverable_vat`, `oman_reverse_charge`, `oman_supply_category`, `oman_tax_evidence`, the rate-history reference, and how the treatment was decided (`oman_vat_source`).

**Resolution order:** user-chosen line treatment → user-chosen line VAT code → Item default code → reverse-charge/import detection for foreign suppliers (configurable `Reverse Charge` rules first) → Item Tax Template mapping, used only when it points to exactly one code → settings default. Values the engine derived are recomputed on every save. Only values the user chose stay fixed.

**Per-document flow:**

* `before_validate` puts the mapped Item Tax Template on each line, so ERPNext itself computes the correct VAT.
* `validate` runs the engine:
  * it reads ERPNext's per-line VAT and checks that it equals *rate × taxable at the tax point*;
  * zero-rated, exempt and out-of-scope lines must carry no VAT;
  * the sum of the lines must reconcile to the VAT tax rows;
  * then the configurable checks run.
* On submit, errors block (`Enforcement Mode = Block`, or `Advisory` for a pilot). The engine then:
  * writes the `Oman VAT Transaction` ledger and a validation log;
  * posts recovery and reverse-charge journals;
  * logs audit events;
  * queues the Fawtara submission.

### Configurable legal checks (`Oman VAT Rule`)

Rules carry: check key, severity, parameters, legal reference, rule-set version, effective dates and conditions (company, treatment, code, party country/registration, supply category, item group, account). Approved rules are versioned. To change one, close it with an *Effective To* date and approve a new rule; approved rules cannot be edited in place.

The seeded checks cover:

* party VAT number format;
* VAT-registered buyer has a VAT number;
* input claim requires a valid supplier VAT number;
* zero-rated evidence;
* export code requires a foreign destination;
* invoice issued within N days of supply (seeded 15, verify);
* duplicate supplier invoice / duplicate VAT claim, using normalised numbers across suppliers that share a VAT number;
* foreign services not under reverse charge;
* imported goods without a Bayan declaration;
* credit/debit note references the original and gives an adjustment reason;
* exchange rate to OMR present;
* bad-debt relief minimum age (seeded 180 days, verify).

The engine also always enforces these invariants: active registration, valid company VAT number, period not closed, no future tax point, treatment valid for the direction, rate correctness, and reconciliation to the tax rows.

### Input VAT recovery

Recovery profiles: Full Recovery, Blocked, Fixed Percentage, Business Use, Standard Apportionment (with a provisional %) and Special Method. A profile must be **Approved** before use.

**How a line's recovery % is chosen:** an explicit line profile → `Oman VAT Recovery Rule` (matching on account, item, item group, cost center, supplier or treatment, with dates and priority) → the settings default.

**Overrides:** a manual percentage needs the override flag, a reason and the **Oman VAT Approver** role. Overrides are audit-logged, and submitted VAT fields cannot be changed afterwards.

**Accounting:** the original input VAT is kept. An `Oman VAT Recovery Allocation` posts the non-recoverable part out of Input VAT. It goes to the line's expense account, or to the *Non-Recoverable VAT* account for stock and fixed-asset lines.

**Year-end:** `Oman VAT Recovery Adjustment` recomputes the actual taxable/total ratio from the ledger and posts the difference.

Example (40%): input VAT 5.000 → recoverable 2.000, non-recoverable 3.000.

### Reverse charge, imports, adjustments

* **Reverse charge.** An `Oman Reverse Charge Entry` posts *Dr RCM Input VAT (recoverable) / Dr non-recoverable / Cr RCM Output VAT*. The supplier payable is never touched. The alternative *Tax Template* mode validates paired add/deduct tax rows instead.
* **Import of goods.** An `Oman Import Declaration` records the Bayan number, dates, customs value, duty, customs-assessed VAT, *Paid at Customs* or *Deferred via VAT Return*, and recovery %. It links to the Purchase Invoices, detects duplicate declarations or claims, and posts the journal.
* **Adjustments.**
  * ERPNext credit and debit notes become adjustment transactions linked to the original invoice, and require a reason.
  * `Oman VAT Adjustment` covers bad-debt relief, change in consideration, incorrect treatment, previous-period corrections, recovery changes and manual statutory adjustments. It records the original transaction, its treatment and period, the reason and evidence.

## 4. Periods, returns and snapshots

**Periods.** `Oman VAT Period` periods are generated per registration (quarterly or monthly) and kept ahead by the scheduler. Posting, cancelling or VAT-account journals inside a **Finalized/Filed/Locked** period are refused. Corrections go through an open-period adjustment.

**Return lifecycle (`Oman VAT Return`):**

| Stage | What happens |
|---|---|
| **Open** | Collect transactions from the ledger into box-level working-paper lines. |
| **Validation** | Flags unrecorded documents, documents submitted with errors, missing zero-rated evidence, pending-evidence claims, and VAT-register ↔ GL differences. |
| **Reviewed** | A manager reviews: zero errors required; warnings must be explicitly accepted. |
| **Finalized** (submit) | Requires segregation of duties: the preparer cannot finalize. Figures are re-collected and must match the reviewed figures. Then it freezes an **Oman VAT Return Snapshot** (box totals, every line, transaction hashes, rules, rates, account mapping, reconciliation) with a SHA-256 hash, links the transactions so they can never be reported twice, and closes the period. |
| **Filed** | An `Oman VAT Filing Record` stores the OTA filing reference, acknowledgement and payment. |
| **Locked** | An `Oman VAT Period Lock` makes the period read-only. Reopening requires an Approver and a reason, and is audited. |

*Verify Snapshot* re-hashes the frozen content and checks the ledger for drift.

The return box layout (`Oman VAT Return Box`, with formulas) is a working layout. Confirm it against the OTA return form in force.

**Reports:**

* Oman VAT Return Working Paper
* Sales VAT Register, Purchase VAT Register
* Zero-Rated Sales, Exempt Supplies
* Reverse Charge Register, Import VAT Register
* Input VAT Recovery, VAT Adjustment Register
* VAT GL Reconciliation, Fawtara Reconciliation

## 5. Fawtara e-invoicing

**Statutory baseline (verified November 2026).** Decision No. 189/2026 (Official Gazette, 9 August 2026) makes e-invoicing mandatory from **1 April 2027** for annual supplies above **OMR 5 million**, and from **1 October 2027** for everyone else.

**Threshold assessment.** The threshold reference periods default to the OTA FAQ position: supplies from 1 April 2026 to 31 March 2027, or expected supplies over the following 12 months. Which treatments count (including reverse-charge supplies) is configurable. *Compute Annual Supplies* on the registration derives the figure from the ledger. Verify it independently, and use the override date if needed.

**Five-corner model.** ERPNext is C1, the supplier's invoicing system. The app never files directly with the OTA. It submits through the configured **accredited service provider (C2)**, which validates, exchanges with the buyer's provider (C3/C4) and reports to the OTA (C5). Portal steps such as account association remain manual operational steps.

```
Sales Invoice → VAT validation → Fawtara mapper → UBL 2.1 / PINT-OM XML → local validation
   → Oman Fawtara Submission (queue) → provider adapter → ASP (C2) → OTA (C5) / buyer (C3/C4)
   → acceptance, OTA reporting/acknowledgement, receipt, archive
```

**What the integration supports:**

* invoices, credit notes (UBL CreditNote, 381), debit notes (383) and self-billing (389, from Purchase Invoices flagged *Self-billed*);
* B2B, B2C and B2G;
* reverse charge (category AE), exports (Z, delivery country) and imports (Bayan reference);
* an RFC 4122 UUID per document;
* an OMR TaxTotal for foreign-currency invoices;
* optional transaction-flag encoding;
* optional XSD validation (upload the schema in settings).

**Submission queue:**

* **Idempotency.** There is one active submission per document. The idempotency key is unique in the database and sent on every attempt.
* **Transient failures** (network errors, timeouts, HTTP 5xx/429) go to **Retry** with exponential backoff (60 s × 2ⁿ, capped). When attempts are exhausted, the submission is flagged *Needs Attention*.
* **Rejections** go to **Rejected**, with each provider error stored in `Oman Fawtara Error Log`. They are **never retried automatically**. A **Fawtara Manager** resubmits after correction, with a reason; the submission gets a new UUID (configurable), and the old one is marked superseded.
* **Provider acceptance vs. OTA reporting** are tracked separately: `provider_accepted_at` vs. `ota_reported_at` / `ota_acknowledged_at`, plus buyer delivery status. A poller follows up both.
* **Records kept:** each attempt is logged in `Oman Fawtara Submission Log`. Receipts are stored in `Oman Fawtara Receipt` (downloadable). The final or provider-stamped XML is archived immutably in `Oman Fawtara Document` with a retention date.
* **Cancelling** an invoice that has been sent to Fawtara is blocked; issue a credit note instead.
* **Scheduler:**

  | Job | Frequency |
  |---|---|
  | Queue | every 5 min |
  | Status poll | every 15 min |
  | Provider connectivity | hourly |
  | Certificate expiry and period generation | daily |

## 6. Provider adapters (no provider is hard-coded)

* **Sandbox (Simulated):** accept, reject, OTA-pending, or transient-failure-then-accept, with idempotent replay. For UAT and tests only. It is blocked in Production.
* **Generic REST:** a configurable base URL and paths; API key, Bearer, Basic or OAuth2 client-credentials authentication; optional mTLS (`Oman Fawtara Certificate`); JSON-with-base64-XML or raw XML payloads; JSON-path mapping of status, references, OTA status, delivery, errors, receipt and stamped XML; and an optional listing endpoint for reconciliation.
* **Your own adapter:** subclass `oman_fawtara.fawtara.providers.base.FawtaraProvider` (`submit`, `get_status`, `ping`, `list_documents`) and register it from any app:

```python
# hooks.py of your integration app
oman_fawtara_provider_adapters = {"Acme ASP": "acme_asp.fawtara.AcmeAdapter"}
```

Raise `TransientProviderError` for retryable problems and `ProviderConfigurationError` for authentication or configuration problems. Return a `ProviderResult` for everything else.

## 7. Roles and segregation of duties

| Role | Can |
|---|---|
| Oman VAT User | Prepare: draft returns, import declarations, adjustments, evidence |
| Oman VAT Manager | Review returns, configure master data, submit adjustments |
| Oman VAT Approver | Approve rules, profiles and legal review; override recovery %; lock and reopen periods; cancel finalized returns |
| Fawtara Operator | Monitor the queue, retry transient failures |
| Fawtara Manager | Provider and certificate setup, authorised resubmission of rejected documents |

Manual Journal Entries on VAT accounts are restricted to VAT Managers by default and are audit-logged.

## 8. Testing

```bash
bench --site <site> run-tests --app oman_fawtara
```

* `tests/test_calc.py` (18 tests) covers the arithmetic, XML and local validation, with no database.
* `tests/test_acceptance.py` (25 tests) creates real ERPNext documents on an OMR company:

| # | Scenario | Expected |
|---|---|---|
| 01 | Domestic standard-rated sale | 5% output VAT, ledger written |
| 02 | Zero-rated sale | 0 VAT, nature Zero Rated, evidence linked |
| 03 | Exempt sale | No output VAT, box 1(c) |
| 04 | Mixed-treatment invoice | Independent per-line calculation |
| 05 | Partially recoverable purchase (40%) | 5.000 → 2.000 / 3.000 + allocation journal |
| 06 | Blocked input VAT | No recovery |
| 07 | Recovery override by non-approver | Rejected |
| 08 | Foreign supplier services | Import of Services, RCM output = input, payable unchanged |
| 09 | Import of goods | Bayan linkage, 52.500 VAT, duplicate declaration refused |
| 10 | Sales credit note | VAT reversal, linked to original, reason required |
| 11 | Foreign currency purchase (USD) | OMR conversion (38.500 / 1.925) |
| 12 | Duplicate supplier invoice (`DUP-0012` vs `dup 12`) | Refused |
| 13 | Closed VAT period | Submission refused |
| 14 | Finalized return | Boxes, reproducible snapshot, immutability, filing, lock |
| 15 | Segregation of duties | Preparer cannot finalize |
| 20 | Accepted submission | Receipt, references, archive; cancel blocked |
| 21 | Provider accepted, OTA pending | Separate status/timestamps; poller acknowledges |
| 22 | Duplicate Fawtara request | No duplicate submission/document (idempotent replay) |
| 23 | Provider rejection | Recorded, no auto-retry, authorised resubmission |
| 24 | Network failure | Safe retry with backoff, single document |
| 25 | XML content | Seller VAT number, OMR tax, UUID |
| 30 | VAT register ↔ GL | Zero differences |
| 31 | Audit hash chain | Intact |
| 32 | Ledger immutability | Edit refused |
| 33 | Effective-dated rates | Correct rate; none before 16 Apr 2021 |

**Verified on this build** (Frappe v16 + ERPNext v16, Python 3.14, MariaDB):

| Check | Result |
|---|---|
| Full suite on brand-new sites (new site → setup wizard → install → run) | 43/43 passed |
| Upgrade path | `bench migrate` passed |
| Uninstall | No custom fields or DocTypes left; ERPNext data intact |
| Reinstall | Passed |
| Volume run: 300 three-line invoices | ≈ 280 ms per invoice including ERPNext GL; 300/300 accepted by the queue in 16 s |
| VAT register vs GL (output, input, reverse charge) after ledger backfill | Reconciled to the baisa across 320 invoices |
| Audit chain over 900 events | Valid |
| Desk smoke test | Workspace, sidebar, dock and invoice actions load with no JavaScript errors |

**Release checklist (outside automated tests):**

* Have an Oman VAT specialist approve test cases and the box layout.
* Confirm the PINT-OM identifiers against the published specification.
* Run conformance tests in the chosen accredited provider's test environment.
* Run volume tests on production-sized data.
* Do a permissions review with real users.

## 9. Assumptions and items to verify before production

* **Rule set to incorporate.** The seeded rule set (`OM-VAT-2026.11-BASELINE`) is a working baseline. It must reflect Royal Decree 121/2020, the Executive Regulations and all amendments, including the 2025 amendment and **Decision 189/2026**.
* **Seeded parameters to confirm** against the current Executive Regulations: the issue-days limit (15), the bad-debt age (180 days), and which supplies count towards the threshold.
* **Return box codes** follow the structure of the OTA return. Confirm the exact layout and numbering against the current form.
* **PINT-OM identifiers** (CustomizationID `urn:peppol:pint:billing-1@om-1`, endpoint scheme, CR scheme, transaction flags) are configurable defaults. Set them from the OTA's published PINT-OM specification and data dictionary.
* **Signing and certificates.** Digital signing is performed by the accredited provider's infrastructure; the app stores client certificates for mTLS only.
* **Credit notes** default to *Net in Original Box*. Switch to *Adjustment Box* if the return form requires it.

## 10. Support

* Documentation: https://docs.thinknxg.com/thinknxgerp
* Support: https://thinknxg.com/support

License: MIT. © 2026 thinkNXG.
