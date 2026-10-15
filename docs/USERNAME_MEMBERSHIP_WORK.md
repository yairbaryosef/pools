# Username membership work

Approved scope: retain SQLite; support existing registered non-email usernames as an explicit alternative to verified email for group membership; display usernames where available. Preserve user-ID authorization and existing data. API.md defines selector semantics. Existing password-account behavior is retained, not replaced by email-only validation.

## Gates
- [x] Test writer: black-box API and browser regression tests authored.
- [ ] Database: normalized username lookup and disposable SQLite integration.
- [ ] Backend: selector validation, resolution, and member response contracts.
- [ ] Frontend: username/email controls and Selenium integration.
- [ ] Verifier: final scoped evidence.

Use only disposable databases for E2E. Preserve the existing port-8000 service. No MySQL migration, deployment, or security-agent review is included.
