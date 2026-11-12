# Runbook: export release (manual delivery with receipt)

Owner: approver role (TBD). The MVP does not include a secure external delivery service. Approval is a decision, not a transfer. An administrator delivers the approved file through an already approved business channel and records a receipt.

Lifecycle: requested, reviewed, approved or rejected, staged, released, expired. The reviewer must differ from the requester; a database constraint enforces this.

## Steps

1. **Request.** The employee selects the object and version, recipient, purpose and classification. Nothing is released by requesting.
2. **Review.** A designated reviewer (not the requester) checks business need, classification, recipient and expiry. Restricted data needs a second reviewer by policy. Approve or reject with a reason; both are audited.
3. **Stage.** A restricted operator stages only the approved object and version into the release area. Do not paste a URL or filesystem path from the request; stage from the recorded object reference. Compute and record a checksum.
4. **Re-validate at release.** Check the employee is still active, the approval has not expired, the destination matches, the object version is unchanged and the request has not been released before. If anything differs, reject and ask for a new request.
5. **Deliver.** Send through the approved channel to the approved recipient only. Do not use personal email or an unapproved cloud drive.
6. **Receipt.** Record release time, channel, recipient confirmation and the checksum in the portal. The release is audited. An authorised recipient can still copy the file; say so in the receipt notes.
7. **Expire.** Remove the staged copy at expiry. Unreleased approvals expire and cannot be used later.

## Rejected attempts to watch for

Self-approval, a changed object version, an expired approval, a substituted recipient, path traversal, arbitrary URL fetching and a second release of the same request (scenario 7).
