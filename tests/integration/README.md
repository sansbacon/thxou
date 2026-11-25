# Integration tests

These tests require a disposable nonproduction Supabase project and authenticated
fixtures. They are intentionally not run by the default unit validation. Never
use a service-role key as the test subject and never send real SMS.
