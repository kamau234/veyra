"""Supabase project credentials for the optional cloud sync add-on.

The publishable (anon) key is a client-side credential by design: it is shipped
inside every Supabase web app and is scoped by row-level security, so embedding
it here is the supported pattern. The service-role secret must never appear in
this file or anywhere in the repository.
"""

SUPABASE_URL = "https://skaxkktadzkzcgrcxtyw.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_Fs4Qga6PxsODqM943ssCuA_whyxh5Hq"
